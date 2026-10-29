"""完整验证样例：导入 → 上下文 → MiniMax 修改 → 测试 → 状态保存 → 重启复用 → 规格更新与替代。

每一步都是新的 Python 进程（模块“重启”），命令、退出码、输出与代码版本写入 evidence/run/。
  python run_demo.py               调用 MiniMax（需要 MINIMAX_API_KEY）
  python run_demo.py --recorded    不调用 MiniMax，使用仓库中已记录的 MiniMax 输出（sample/after）
数据库与 PowerContext 连接见 README.md；每次运行使用新的项目 ID 与 scope，从空状态开始。
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'evidence' / 'run'
TARGET_TESTS = ['FeatureTests']          # 目标功能测试（修改前必须失败）
REGRESSION_TESTS = ['RegressionTests']   # 原有行为回归测试（修改前后都必须通过）
steps = []


def git(*args):
    try:
        return subprocess.run(['git', '-C', str(ROOT), *args], capture_output=True, text=True).stdout.strip() or None
    except OSError:
        return None


def step(name, command, env=None, expect=0, parse=True):
    run = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                         env=dict(os.environ, PYTHONIOENCODING='utf-8', **(env or {})))
    record = {'step': name, 'command': command, 'exit_code': run.returncode,
              'stdout': run.stdout, 'stderr': run.stderr}
    steps.append(record)
    print(f'[{run.returncode}] {name}', flush=True)
    if expect is not None and run.returncode != expect:
        raise SystemExit(f'{name}: 期望退出码 {expect}，实际 {run.returncode}\n{run.stderr[-2000:]}')
    return json.loads(run.stdout) if parse and run.stdout.strip().startswith(('{', '[')) else record


def unittest(code_dir, tests_dir, names):
    return [sys.executable, '-B', '-m', 'unittest', '-v',
            *[f'test_task_service.{name}' for name in names]], {'PYTHONPATH': os.pathsep.join([str(code_dir), str(tests_dir)])}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def wait_for_services(seconds):
    """seekdb 首次启动约需 1 分钟：轮询数据库与 PowerContext，就绪后再开始。"""
    import pymysql
    base = os.getenv('PC_URL', 'http://127.0.0.1:18752').rstrip('/')
    checks = (('seekdb', lambda: pymysql.connect(host=os.getenv('DB_HOST', '127.0.0.1'),
                  port=int(os.getenv('DB_PORT', '18753')), user=os.getenv('DB_USER', 'root'),
                  password=os.getenv('DB_PASSWORD', ''), connect_timeout=5).close()),
              ('PowerContext', lambda: urllib.request.urlopen(base + '/v1/scopes', timeout=5)))
    deadline = time.time() + seconds
    for name, check in checks:
        while True:
            try:
                check()
                break
            except urllib.error.HTTPError:
                break                      # 服务已应答（GET 不被允许也说明已启动）
            except Exception as error:
                if time.time() > deadline:
                    raise SystemExit(f'{name} 在 {seconds} 秒内未就绪：{error!r}')
                time.sleep(3)
        print(f'{name} ready', flush=True)


def save(py, scope_id, temporary, name, state):
    path = Path(temporary) / f'{name}.json'
    path.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
    return step(name, [*py, 'save', '--scope', scope_id, '--state', str(path)])


def verification(ctx, stage):
    return next(v for v in ctx['progress']['verification'] if v['stage'] == stage)


def history(ctx):
    """已有验证结果原样保留为历史（去掉本次判定字段，下次读取时重新判定）。"""
    return [{k: v for k, v in r.items() if k not in ('validity', 'changed')} for r in ctx['progress']['verification']]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--recorded', action='store_true', help='使用已记录的 MiniMax 输出，不调用 API')
    parser.add_argument('--wait', type=int, default=300, help='等待 seekdb 与 PowerContext 就绪的最长秒数')
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    wait_for_services(args.wait)
    run_id = uuid.uuid4().hex[:12]
    project, task = f'taskboard-{run_id}', 'TASK-2'
    py = [sys.executable, str(ROOT / 'context.py')]
    # minimax_tree：minimax/ 目录的 git tree 哈希，与提交历史无关，目录内容相同即相同
    summary = {'run_id': run_id, 'git_revision': git('rev-parse', 'HEAD'),
               'minimax_tree': git('rev-parse', 'HEAD:minimax'), 'project': project, 'task': task,
               'minimax': 'recorded' if args.recorded else 'live'}
    contexts = {}
    try:
        with tempfile.TemporaryDirectory() as temporary:
            # 独立副本：工作代码、规格更新、MiniMax 输出都写在副本中，仓库原始样例不变
            sample = Path(temporary) / 'sample'
            shutil.copytree(ROOT / 'sample', sample, ignore=shutil.ignore_patterns('__pycache__'))
            work = sample / 'work'
            work.mkdir()
            shutil.copy(sample / 'before' / 'task_service.py', work / 'task_service.py')
            # 工作清单：代码来源指向工作副本（初始为 before/ 快照），修改后重新导入即可让上下文看到当前代码
            data = json.loads((sample / 'manifest.json').read_text(encoding='utf-8'))
            for item in data['sources']:
                if item['kind'] == 'code':
                    item['path'] = 'work/task_service.py'
            manifest = sample / 'manifest-work.json'
            manifest.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
            ingest = [*py, 'ingest', '--project', project, '--manifest', str(manifest)]

            # 1. 导入资料到 seekdb
            summary['ingest'] = step('ingest', ingest)
            # 2. PowerContext：新 scope，从空状态开始保存任务记录
            scope_id = step('scope', [*py, 'scope', '--key', f'minimax-demo-{run_id}'])['scope_id']
            summary['scope_id'] = scope_id
            ctx_args = [*py, 'context', '--project', project, '--task', task, '--scope', scope_id]
            contexts['context-initial'] = initial = step('context-initial', ctx_args)
            assert initial['progress']['completed'] == [] and initial['progress']['verification'] == [], '新 scope 应为空状态'
            save(py, scope_id, temporary, 'save-start', {'task': task, 'completed': ['导入规格、代码与测试到 seekdb'],
                 'todo': ['由 MiniMax 依据上下文修改代码', '运行功能与回归测试'], 'tests': []})

            # 3. 修改前：目标功能测试失败（目标行为未实现），回归测试通过
            command, env = unittest(work, sample, TARGET_TESTS)
            before_target = step('tests-before-target', command, env, expect=1, parse=False)
            command, env = unittest(work, sample, REGRESSION_TESTS)
            step('tests-before-regression', command, env, expect=0, parse=False)
            # 修改前的失败必须是断言失败（行为未实现），不能是导入错误等环境问题
            verdict = before_target['stderr'].strip().splitlines()[-1]
            assert 'failures=' in verdict and 'errors=' not in verdict, verdict
            before_sha = sha(work / 'task_service.py')
            save(py, scope_id, temporary, 'save-before-tests', {'task': task,
                 'completed': ['导入规格、代码与测试到 seekdb', '修改前测试：功能测试断言失败、回归测试通过'],
                 'todo': ['由 MiniMax 依据上下文修改代码', '修改后运行功能与回归测试'],
                 'tests': [{'stage': 'before', 'target_exit': 1, 'regression_exit': 0, 'code_sha256': before_sha,
                            'basis': initial['basis']}]})

            # 4. 重启后的上下文读取已保存的状态（含仍适用的修改前验证结果），再交给 MiniMax
            contexts['context-before-change'] = resumed = step('context-before-change', ctx_args)
            assert resumed['progress']['todo'], '重启后应读到已保存的待办'
            assert verification(resumed, 'before')['validity'] == 'current', '代码未变时修改前验证应仍适用'
            if args.recorded:
                shutil.copy(sample / 'after' / 'task_service.py', work / 'task_service.py')
                step('minimax-recorded', [sys.executable, '-c', 'print("使用仓库中已记录的 MiniMax 输出")'], parse=False)
            else:
                step('minimax', [sys.executable, str(ROOT / 'minimax_agent.py'), '--project', project,
                                 '--task', task, '--scope', scope_id, '--output', str(work / 'task_service.py')])
                # 实时输出另存到本次运行目录，不覆盖仓库中已提交的 sample/after
                shutil.copy(work / 'task_service.py', OUT / 'minimax-live-task_service.py')
            after_sha = sha(work / 'task_service.py')

            # 5. 重新导入修改后的代码：修改前的验证结果仍保留，但标记为不再适用于当前代码
            step('ingest-after-change', ingest)
            contexts['context-after-change'] = changed = step('context-after-change', ctx_args)
            old = verification(changed, 'before')
            assert old['validity'] == 'stale' and 'code' in old['changed'], old
            if args.recorded:
                assert changed['progress']['needs_reverification'], '代码变化后应提示重新验证'
            else:
                # 实时模式：MiniMax 自检记录绑定了本轮输出的代码版本，重新导入后仍适用
                assert verification(changed, 'minimax-self-check')['validity'] == 'current'

            # 6. 修改后：同一组目标测试与回归测试全部通过
            command, env = unittest(work, sample, TARGET_TESTS)
            step('tests-after-target', command, env, expect=0, parse=False)
            command, env = unittest(work, sample, REGRESSION_TESTS)
            step('tests-after-regression', command, env, expect=0, parse=False)
            tests_sha = sha(sample / 'test_task_service.py')

            # 7. 保存验证结果（绑定当前规格、代码、测试版本）；重启后的上下文使用这些结果
            save(py, scope_id, temporary, 'save-done', {'task': task,
                 'completed': ['导入规格、代码与测试到 seekdb', 'MiniMax 依据上下文完成代码修改', '功能测试与回归测试通过'],
                 'todo': [],
                 'tests': history(changed) + [{'stage': 'after', 'target_exit': 0, 'regression_exit': 0,
                                               'code_sha256': after_sha, 'tests_sha256': tests_sha,
                                               'basis': changed['basis']}]})
            contexts['context-restored'] = restored = step('context-restored', ctx_args)
            progress = restored['progress']
            assert progress['todo'] == [] and progress['verification_status'] == 'current', progress
            assert verification(restored, 'after')['validity'] == 'current'
            assert verification(restored, 'before')['validity'] == 'stale'

            # 8. 规格更新并重新导入：上下文使用新内容，原验证结果标记为依据的规格已变化、需重新验证
            marker = f'更新标记 {run_id}：status 参数也接受 None 以外的空白字符串时报错'
            with (sample / 'spec.md').open('a', encoding='utf-8') as stream:
                stream.write(f'\n## TASK-2 规格补充\n{marker}\n')
            step('ingest-updated', ingest)
            contexts['context-updated'] = updated = step('context-updated', ctx_args)
            target = next(e for e in updated['spec_entries'] if e['role'] == 'implement')
            assert marker in target['text'], '重新导入后应返回更新的规格'
            stale = verification(updated, 'after')
            assert stale['validity'] == 'stale' and stale['changed'] == ['spec'], stale
            assert updated['progress']['needs_reverification'] and updated['progress']['todo'], updated['progress']

            # 9. 规格替代：新条目声明替代 TASK-1 后，TASK-1 不再作为要求下发，单独列为已失效
            with (sample / 'spec.md').open('a', encoding='utf-8') as stream:
                stream.write('\n## TASK-3 原有行为修订\n> 替代：TASK-1\n'
                             '不传筛选条件时返回全部任务的新列表，保持输入顺序，不修改输入。\n')
            step('ingest-superseded', ingest)
            contexts['context-superseded'] = superseded = step('context-superseded', ctx_args)
            active = {e['entry_id']: e['role'] for e in superseded['spec_entries']}
            inactive = {e['entry_id']: e for e in superseded['inactive_spec_entries']}
            assert 'TASK-1' not in active and active.get('TASK-3') == 'preserve', active
            assert inactive['TASK-1']['status'] == 'superseded' and inactive['TASK-1']['by'] == 'TASK-3', inactive

            summary.update({'before_sha256': before_sha, 'after_sha256': after_sha, 'tests_sha256': tests_sha,
                            'result': 'PASS'})
            print('PASS')
    finally:
        for name, value in contexts.items():
            (OUT / f'{name}.json').write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        (OUT / 'steps.json').write_text(json.dumps(steps, ensure_ascii=False, indent=2), encoding='utf-8')
        (OUT / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
