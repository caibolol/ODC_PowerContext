"""MiniMax 开发助手：用 context.py 给出的上下文完成代码修改，并记录全过程。

流程：
  1. 调用 context.py 的 context（新进程），得到 seekdb 中的规格条目、代码符号、测试和 PowerContext 状态；
  2. 把上下文（不含任何参考实现）发给 MiniMax Chat Completions，要求返回修改后的完整文件；
  3. 写入 --output，保存请求、回复（<think> 段落已脱敏）、代码差异到证据目录
     （默认 evidence/minimax-api，可用 --evidence-dir 指定本次运行的目录）；
  4. 把“MiniMax 已修改、待运行测试”写回 PowerContext，供下一次上下文使用。

环境变量：MINIMAX_API_KEY（必填，不写入任何文件）、MINIMAX_BASE_URL（默认 https://api.minimaxi.com/v1）、
MINIMAX_MODEL（默认 MiniMax-M3），以及 context.py 的数据库与 PowerContext 变量。
"""
import argparse
import datetime
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parent
EVIDENCE = ROOT / 'evidence' / 'minimax-api'
CODE_BLOCK = re.compile(r'```(?:python|py)?\s*\n(.*?)```', re.S)

SYSTEM = (
    '你是参与规格驱动开发（SDD）的代码助手。只依据给出的规格条目修改代码：'
    '实现标记为 implement 的条目，同时保持标记为 preserve 的条目描述的原有行为。'
    '不要修改测试，不要引入新依赖。只回复一个 Python 代码块，内容是修改后的完整文件。'
)

THINK = re.compile(r'<think>.*?</think>', re.S)
REDACTION_NOTE = '[已脱敏：模型私有思维链未随作品交付]'


def redact_thinking(value):
    """递归移除 <think> 段落。

    作品不提交模型私有思维链；响应 ID、usage、代码与测试结果原样保留。
    """
    if isinstance(value, str):
        return THINK.sub(REDACTION_NOTE, value)
    if isinstance(value, list):
        return [redact_thinking(item) for item in value]
    if isinstance(value, dict):
        return {key: redact_thinking(item) for key, item in value.items()}
    return value


def run_context(args):
    command = [sys.executable, str(ROOT / 'context.py'), 'context',
               '--project', args.project, '--task', args.task, '--scope', args.scope]
    run = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                         env=dict(os.environ, PYTHONIOENCODING='utf-8'))
    if run.returncode:
        raise SystemExit('context 失败：' + run.stderr)
    return command, json.loads(run.stdout)


def build_prompt(ctx):
    sources = {row['path']: row['content'] for row in ctx['sources']}
    lines = [f"任务：{ctx['task']}（项目 {ctx['project']}）", '', '## 适用规格条目（来自 seekdb）']
    for entry in ctx['spec_entries']:
        lines += [f"### [{entry['role']}] {entry['source']} 第{entry['lines'][0]}-{entry['lines'][1]}行 {entry['title']}",
                  entry['text'], '']
    lines.append('## 需要修改的代码')
    for target in ctx['code_targets']:
        lines += [f"- {target['source']}（{target['type']}，第{target['lines'][0]}-{target['lines'][1]}行）"]
    for path in sorted({t['path'] for t in ctx['code_targets']}):
        lines += ['', f'文件 {path} 当前内容：', '```python', sources[path].rstrip(), '```']
    lines += ['', '## 验证测试（不得修改）',
              '功能测试：' + ', '.join(ctx['tests']['functional']),
              '回归测试：' + ', '.join(ctx['tests']['regression'])]
    for path in sorted({s.split('#')[0] for s in ctx['tests']['functional'] + ctx['tests']['regression']}):
        lines += ['', f'测试文件 {path}：', '```python', sources[path].rstrip(), '```']
    progress = ctx['progress']
    lines += ['', '## 任务进展（来自 PowerContext）',
              '已完成：' + ('；'.join(progress['completed']) or '无'),
              '待办：' + ('；'.join(progress['todo']) or '无')]
    lines += ['', '请返回修改后的完整代码文件。']
    return '\n'.join(lines)


def call_minimax(messages, model, base_url, key):
    body = {'model': model, 'messages': messages, 'temperature': 0.2, 'max_tokens': 8192}
    request = urllib.request.Request(base_url.rstrip('/') + '/chat/completions',
                                     json.dumps(body).encode(),
                                     {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key})
    started = time.time()
    with urllib.request.urlopen(request, timeout=300) as response:
        reply = json.load(response)
    return body, reply, round(time.time() - started, 2)


def target_module(ctx):
    """待修改代码对应的模块名，例如 before/task_service.py → task_service。"""
    return Path(ctx['code_targets'][0]['path']).stem


def check_output_name(ctx, output):
    """生成**前**的校验：输出文件名必须与目标模块一致。

    此时文件通常还不存在（模型还没生成），因此只校验名字，不校验存在性。
    名字不一致会让测试导入到别的模块上，必须在调用模型之前就拒绝。
    """
    module = target_module(ctx)
    output = Path(output)
    if output.name != module + '.py':
        raise SystemExit(f'输出文件名 {output.name} 与目标模块 {module}.py 不一致，'
                         f'测试将导入到别的模块上')
    return module


def check_output_exists(ctx, output):
    """生成**后**、运行测试前的校验：本轮输出文件必须真实存在，且名字仍与目标模块一致。

    路径配置错误要明确失败，不能吞掉——否则测试会跑到别处的同名模块上。
    """
    module = check_output_name(ctx, output)
    if not Path(output).is_file():
        raise SystemExit(f'输出文件不存在: {output}')
    return module


def run_tests(ctx, output):
    """用上下文中的测试文件（seekdb 中的内容）运行功能与回归测试。

    每轮都在**全新的临时目录**里执行：本轮产出的源码与上下文中的测试文件都复制进去，
    只从该目录导入。这样保证测的确实是本轮产出的源码，也不会继承输出目录里上一轮
    遗留的 __pycache__。

    为什么必须用全新目录：Python 的字节码缓存以「源码 mtime（秒级）+ 字节数」校验，
    同样字节数、同样 mtime 秒值的**错误源码**会直接命中上一轮留下的 .pyc，
    于是错误代码被判为通过。全新目录里没有任何缓存，问题从根上消失。
    """
    module = check_output_exists(ctx, output)
    names = ctx['tests']['functional'] + ctx['tests']['regression']
    paths = sorted({name.split('#')[0] for name in names})
    ids = [Path(name.split('#')[0]).stem + '.' + name.split('#')[1] for name in names]
    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary)
        # 本轮产出的源码：按原始字节复制，不做任何换行转换
        shutil.copyfile(Path(output).resolve(), work / (module + '.py'))
        for path in paths:
            content = next(row['content'] for row in ctx['sources'] if row['path'] == path)
            (work / Path(path).name).write_text(content, encoding='utf-8')
        command = [sys.executable, '-B', '-m', 'unittest', '-v', *ids]
        env = dict(os.environ, PYTHONPATH=str(work))
        # 模型给出的代码若有语法错误或导入异常，这里会变成测试失败（退出码非 0），
        # 而不是直接中断流程——失败输出要交回模型继续修改。
        run = subprocess.run(command, cwd=work, env=env, capture_output=True, text=True)
    return {'command': ['python', '-B', '-m', 'unittest', '-v', *ids], 'exit_code': run.returncode,
            'output': run.stdout + run.stderr}


class NoCodeBlockError(Exception):
    """模型的回复里没有可用的 Python 代码块。"""


def extract_code(content):
    content = re.sub(r'<think>.*?</think>', '', content, flags=re.S)
    blocks = CODE_BLOCK.findall(content)
    if not blocks:
        raise NoCodeBlockError('MiniMax 回复中没有 Python 代码块')
    return blocks[-1].rstrip() + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--project')
    parser.add_argument('--task')
    parser.add_argument('--scope')
    parser.add_argument('--context-file', help='使用已保存的 context.py 输出（例如 CI 中真实服务给出的上下文），'
                        '不再连接数据库；此时不写回 PowerContext')
    parser.add_argument('--output', required=True, help='写入 MiniMax 修改后文件的路径')
    parser.add_argument('--evidence-dir', help='本次运行的证据目录（默认 evidence/minimax-api）')
    parser.add_argument('--max-rounds', type=int, default=3, help='测试失败时把输出交回 MiniMax 的最多轮数')
    args = parser.parse_args()
    key = os.environ.get('MINIMAX_API_KEY')
    if not key:
        raise SystemExit('请设置环境变量 MINIMAX_API_KEY')
    model = os.getenv('MINIMAX_MODEL', 'MiniMax-M3')
    base_url = os.getenv('MINIMAX_BASE_URL', 'https://api.minimaxi.com/v1')

    if args.context_file:
        ctx = json.loads(Path(args.context_file).read_text(encoding='utf-8'))
        context_command = ['(file)', 'context-file', str(args.context_file),
                           'sha256=' + hashlib.sha256(Path(args.context_file).read_bytes()).hexdigest()]
        args.task = args.task or ctx['task']
    elif not (args.project and args.task and args.scope):
        raise SystemExit('需要 --project --task --scope，或 --context-file')
    else:
        context_command, ctx = run_context(args)
    if len(ctx['code_targets']) != 1:
        raise SystemExit('本样例要求恰好一个待修改的代码文件')
    target = ctx['code_targets'][0]
    before = next(row['content'] for row in ctx['sources'] if row['path'] == target['path'])
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    # 生成前先校验：文件名必须与目标模块一致（此时文件还不存在，允许不存在）
    check_output_name(ctx, output)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    evidence = Path(args.evidence_dir).resolve() if args.evidence_dir else EVIDENCE
    evidence.mkdir(parents=True, exist_ok=True)
    try:
        exchange_path = (evidence / f'{stamp}-exchange.json').relative_to(ROOT).as_posix()
    except ValueError:
        exchange_path = str(evidence / f'{stamp}-exchange.json')
    messages = [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': build_prompt(ctx)}]
    rounds, after, seconds, reply = [], before, 0.0, {}
    produced = False
    for number in range(1, args.max_rounds + 1):
        request, reply, elapsed = call_minimax(messages, model, base_url, key)
        seconds += elapsed
        content = reply['choices'][0]['message']['content']
        try:
            after = extract_code(content)
        except NoCodeBlockError as error:
            # 模型没给出可用的代码：同样作为「本轮失败」交回模型继续修改，
            # 不能直接中断——否则这一轮的请求与回复就丢了。
            test_run = {'command': ['(模型回复中没有代码块)'], 'exit_code': 1, 'output': str(error)}
            rounds.append({'round': number, 'elapsed_seconds': elapsed, 'request': request, 'response': reply,
                           'code_sha256': None, 'tests': test_run})
            print(f'round {number}: {error}', file=sys.stderr, flush=True)
            messages = messages + [{'role': 'assistant', 'content': content},
                                   {'role': 'user', 'content': '你的回复里没有可用的 Python 代码块。'
                                    '请只回复一个 Python 代码块，内容是修改后的完整文件。'}]
            continue
        # 按 MiniMax 原样字节写入（不做换行转换），与记录中的 SHA-256 一致
        output.write_text(after, encoding='utf-8', newline='\n')
        produced = True
        # 生成后、运行测试前：校验本轮输出文件真实存在
        check_output_exists(ctx, output)
        # 开发助手的自检：运行上下文给出的功能与回归测试。
        # 语法错误、导入异常、断言失败都表现为测试失败（退出码非 0），
        # 失败输出会交回模型继续修改，不会提前中断整个流程。
        test_run = run_tests(ctx, output)
        rounds.append({'round': number, 'elapsed_seconds': elapsed, 'request': request, 'response': reply,
                       'code_sha256': hashlib.sha256(after.encode()).hexdigest(), 'tests': test_run})
        print(f'round {number}: tests exit {test_run["exit_code"]}', file=sys.stderr, flush=True)
        if test_run['exit_code'] == 0:
            break
        # 测试失败时把失败输出交给 MiniMax 继续修改
        messages = messages + [{'role': 'assistant', 'content': content},
                               {'role': 'user', 'content': '运行上下文中的测试未全部通过，输出如下。请依据规格条目修正，'
                                '不要修改测试，再返回完整代码文件。\n```\n' + test_run['output'][-4000:] + '\n```'}]
    diff = ''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                        f"a/{target['path']}", f'b/{output.as_posix()}')) if produced else ''
    record = {
        'time_utc': stamp, 'endpoint': base_url.rstrip('/') + '/chat/completions', 'model': model,
        'elapsed_seconds': round(seconds, 2), 'context_command': context_command[1:],
        'context_sources': {'spec_entries': [e['source'] for e in ctx['spec_entries']],
                            'code_targets': [t['source'] for t in ctx['code_targets']],
                            'tests': ctx['tests'], 'seekdb_queries': ctx['query']['all_queries']},
        'rounds': redact_thinking(rounds),   # 每轮完整请求（不含 Authorization 头）、回复与测试结果；<think> 段落已脱敏
        'output_file': output.as_posix(),
        'before_sha256': hashlib.sha256(before.encode()).hexdigest(),
        # 没有产出代码时 after_sha256 为 None：不能拿修改前的哈希冒充产出
        'after_sha256': hashlib.sha256(after.encode()).hexdigest() if produced else None,
        '_redaction': '回复中的模型私有思维链段落（think 标签包裹）已替换为占位说明，不随作品提交；'
                      '响应 ID、usage、生成的代码与测试结果原样保留。',
    }
    (evidence / f'{stamp}-exchange.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    (evidence / f'{stamp}-change.diff').write_text(diff, encoding='utf-8', newline='\n')
    if rounds[-1]['tests']['exit_code'] != 0:
        raise SystemExit(f'MiniMax 在 {len(rounds)} 轮内未使测试通过，记录见 {exchange_path}')

    if args.context_file:
        print(json.dumps({'model': model, 'elapsed_seconds': seconds, 'output': output.as_posix(),
                          'exchange': f'{exchange_path}',
                          'usage': reply.get('usage')}, ensure_ascii=False, indent=2))
        return
    # 任务进展写回 PowerContext：下一次 context 会看到“已修改、待测试”
    state = {'task': args.task,
             'completed': ctx['progress']['completed'] + [f'MiniMax（{model}）已依据上下文修改 {target["symbol"]}'],
             'todo': ['运行功能测试与回归测试并记录结果'],
             'tests': ctx['progress']['verification'],
             'minimax_exchange': f'{exchange_path}'}
    with tempfile.TemporaryDirectory() as temporary:
        state_file = Path(temporary) / 'state.json'
        state_file.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
        save = subprocess.run([sys.executable, str(ROOT / 'context.py'), 'save', '--scope', args.scope,
                               '--state', str(state_file)], capture_output=True, text=True, encoding='utf-8',
                              env=dict(os.environ, PYTHONIOENCODING='utf-8'))
    if save.returncode:
        raise SystemExit('保存任务状态失败：' + save.stderr)
    print(json.dumps({'model': model, 'elapsed_seconds': seconds, 'output': output.as_posix(),
                      'exchange': f'{exchange_path}',
                      'usage': reply.get('usage')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
