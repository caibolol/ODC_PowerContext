"""交付材料一致性自检：按官方六项必做项逐项判定交付目录内的材料是否齐备、自洽。

用法（在 minimax/ 目录下）：
    python verify_acceptance.py

只读取交付目录内的文件，不访问数据库、不联网、不需要本机 WorkBuddy 安装。
全部通过时退出码为 0，任一项不通过为 1。

**这个脚本的边界**：它只核对「交付材料之间是否一致、是否真实存在于提交中」。
它**不能**认证模型服务商来源、不能证明回复确实由某个服务商生成，也**不能代替官方验收**。
官方评分以平台记录的固定提交为准。

题面六项：
  1 能够运行      按运行说明可以初始化数据、启动模块并执行验证样例，不依赖未交付的本地文件或状态
  2 MiniMax 实际参与  开发记录包含本次任务、提供的上下文和代码修改过程，并与提交的代码差异对应
  3 上下文正确    输出包含样例规定的必要规格、代码和测试来源；规格更新并重新导入后，输出使用更新内容
  4 数据库实际参与  seekdb／OceanBase 中保存了工程资料或索引，实际查询结果用于任务上下文
  5 状态能够复用  从空状态开始保存任务记录，重启模块后能够读取，并用于后续上下文或任务处理
  6 代码修改有效  同一组目标功能测试在修改前因目标行为未实现而失败，修改后全部通过；相关回归测试也全部通过
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from minimax_agent import NoCodeBlockError, build_prompt, extract_code  # noqa: E402

results = []
# 有效的 SHA-256：64 位小写十六进制
SHA256_RE = re.compile(r'[0-9a-f]{64}')


def check(item, name, ok, detail):
    results.append((item, name, bool(ok), detail))


def read_json(relative):
    return json.loads((ROOT / relative).read_text(encoding='utf-8'))


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sha256_lf(path):
    return hashlib.sha256(Path(path).read_bytes().replace(b'\r\n', b'\n')).hexdigest()


# ---------------------------------------------------------------- 1 能够运行
need = ['README.md', 'TECHNICAL.md', 'ACCEPTANCE.md', 'DEVELOPMENT.md', 'requirements.txt',
        'requirements-windows-lock.txt', 'context.py', 'minimax_agent.py', 'run_demo.py',
        'verify_sample.py', 'verify_context.py', 'verify_platform_record.py', 'test_tooling.py',
        'start-seekdb.ps1', 'start-powercontext.ps1',
        'sample/spec.md', 'sample/manifest.json', 'sample/test_task_service.py',
        'sample/before/task_service.py', 'sample/after/task_service.py']
missing = [p for p in need if not (ROOT / p).exists()]
check(1, '必需文件齐备', not missing, f'缺失 {missing}' if missing else f'{len(need)} 个必需文件全部存在')

# 安装依赖不得指向队伍私有仓库（评审干净环境无私有凭据）
install_files = ['requirements.txt', 'requirements-windows-lock.txt']
private = []
for name in install_files:
    text = (ROOT / name).read_text(encoding='utf-8')
    for line in text.splitlines():
        if 'git+' in line and 'github.com/' in line and 'oceanbase/powercontext' not in line:
            private.append(f'{name}: {line.strip()}')
readme = (ROOT / 'README.md').read_text(encoding='utf-8')
for line in readme.splitlines():
    if 'pip install' in line and 'git+' in line and 'oceanbase/powercontext' not in line:
        private.append(f'README.md: {line.strip()}')
check(1, '依赖来自公开仓库', not private, '; '.join(private) if private else 'requirements 与 README 安装命令均指向 oceanbase/powercontext')

# 交付的运行证据必须是 PASS
run = read_json('evidence/run/summary.json')
steps = read_json('evidence/run/steps.json')
check(1, '验证样例已跑通', run.get('result') == 'PASS',
      f"run_id={run.get('run_id')} git_revision={run.get('git_revision')} result={run.get('result')}")

# 每个步骤都要有命令与退出码
bad = [s['step'] for s in steps if 'command' not in s or 'exit_code' not in s]
check(1, '步骤日志含命令与退出码', not bad, f'{len(steps)} 步均有 command/exit_code' if not bad else str(bad))

# 验收文档必须引用**归档在交付中**的真实运行记录，避免文档与证据脱节。
# 注意：不能拿根目录的 summary.json 来比——评审自行复跑后它会被更新，
# 文档引用的是交付时归档的那次运行（evidence/run/<运行编号>/）。
acceptance_text = (ROOT / 'ACCEPTANCE.md').read_text(encoding='utf-8')
cited_runs = set(re.findall(r'\b[0-9a-f]{12}\b', acceptance_text))
cited_revisions = set(re.findall(r'\b[0-9a-f]{40}\b', acceptance_text))
archived = {}
for run_dir in (ROOT / 'evidence' / 'run').glob('*/summary.json'):
    try:
        record = json.loads(run_dir.read_text(encoding='utf-8'))
    except ValueError:
        continue
    archived[record.get('run_id')] = (record.get('git_revision'), run_dir.parent)
matched = [rid for rid in cited_runs
           if rid in archived and archived[rid][0] in cited_revisions]
missing_archives = [rid for rid in cited_runs if rid not in archived]
if matched and not missing_archives:
    detail = (f'文档引用 {sorted(cited_runs)}，其中 {sorted(matched)} 在 evidence/run/ 下有归档，'
              f'且归档的提交号与文档一致')
elif missing_archives:
    detail = f'文档引用的运行 {sorted(cited_runs)} 中未归档的有 {missing_archives}'
else:
    detail = (f'文档引用的运行 {sorted(cited_runs)} 的提交号与归档 {sorted(cited_revisions)} 对不上')
check(1, '验收文档引用归档的真实运行记录',
      bool(cited_runs) and bool(cited_revisions) and bool(matched) and not missing_archives,
      detail)

# 根目录的「最近一次成功运行」必须也能在归档里找到对应记录
top_run = run.get('run_id')
check(1, '最近一次成功运行有归档副本', top_run in archived,
      f'evidence/run/summary.json 的 run_id={top_run} '
      f'{"在归档中" if top_run in archived else "缺少归档"}')

# ------------------------------------------------------- 2 MiniMax 实际参与
platform = ROOT / 'evidence' / 'workbuddy-minimax' / 'platform-record'
session = read_json('evidence/workbuddy-minimax/platform-record/session.json')
model = session.get('model', '')
session_id = session.get('id', '')
check(2, '平台记录了本轮模型', bool(model), f"session={session_id} model={model}")

# 模型必须是 MiniMax 系列：无关模型名应当失败
check(2, '模型名属于 MiniMax', 'minimax' in model.lower(),
      f"model={model!r} 含 minimax" if 'minimax' in model.lower() else f"model={model!r} 与 MiniMax 无关")

# 会话 ID 必须与变更记录关联：错配的会话应当失败
change_files = sorted(platform.glob('changes-*.json'))
change_ids = []
for path in change_files:
    change_ids.append(json.loads(path.read_text(encoding='utf-8'))['change'].get('conversationId'))
check(2, '会话 ID 与变更记录关联', bool(change_files) and all(cid == session_id for cid in change_ids),
      f'{len(change_files)} 份变更记录的 conversationId 均为 {session_id}'
      if change_files and all(cid == session_id for cid in change_ids)
      else f'变更记录 conversationId={set(change_ids)} 与 session.id={session_id} 不一致')

# 由平台改动日志重建业务代码，与提交文件比对
rebuilt = None
for path in change_files:
    change = json.loads(path.read_text(encoding='utf-8'))['change']
    for item in change['files']:
        if item['filePath'].endswith('wb-work' + chr(92) + 'task_service.py'):
            lines = []
            for hunk in item['hunks']:
                for line in hunk['lines']:
                    if line.startswith(('+++', '---')):
                        continue
                    if line.startswith(('+', ' ')):
                        lines.append(line[1:])
            rebuilt = '\n'.join(lines) + '\n'
check(2, '平台改动日志含业务代码 hunk', rebuilt is not None,
      'changes-*.json 中找到 task_service.py 的 unified-diff hunk' if rebuilt else '未找到')

delivered = sha256_lf(ROOT / 'sample' / 'after' / 'task_service.py')
rebuilt_sha = hashlib.sha256(rebuilt.encode('utf-8')).hexdigest() if rebuilt else ''
check(2, '模型产出与提交代码逐字节对应', rebuilt_sha == delivered and bool(rebuilt_sha),
      f'平台重建 {rebuilt_sha[:16]}… == 提交 {delivered[:16]}…' if rebuilt_sha == delivered
      else f'平台重建 {rebuilt_sha[:16]}… != 提交 {delivered[:16]}…')

# 送入的上下文与统一差异
ctx = read_json('evidence/workbuddy-minimax/context-before-change.json')
diff = (ROOT / 'evidence' / 'workbuddy-minimax' / 'change.diff').read_text(encoding='utf-8')
has_task = any(e['role'] == 'implement' and e['entry_id'] == 'TASK-2' for e in ctx['spec_entries'])
check(2, '开发记录含任务与上下文', has_task and 'task_service.py' in diff and ctx.get('task') == 'TASK-2',
      f"任务 {ctx.get('task')}，送入规格 {len(ctx['spec_entries'])} 条，差异 {len(diff.splitlines())} 行")

# 更早的独立 MiniMax API 记录（机器级）
api_files = sorted((ROOT / 'evidence' / 'minimax-api').glob('*-exchange.json'))
api_ok = False
api_detail = '无 API 记录'
api_rounds = []
api_model = ''
if api_files:
    api = json.loads(api_files[0].read_text(encoding='utf-8'))
    api_rounds = api.get('rounds') or []
    api_model = api.get('model', '')
    # 每一轮都必须有请求、原始回复、代码哈希与测试结果
    required = ('round', 'request', 'response', 'code_sha256', 'tests')
    missing = [r.get('round') for r in api_rounds
               if any(not r.get(key) for key in required)]
    responses_ok = all(r['response'].get('id') and r['response'].get('usage')
                        for r in api_rounds)
    api_ok = (bool(api.get('endpoint')) and 'minimax' in api_model.lower()
              and bool(api_rounds) and not missing and responses_ok)
    api_detail = (f"endpoint={api.get('endpoint')} model={api_model} rounds={len(api_rounds)}"
                  + (f" 缺字段的轮次={missing}" if missing else '')
                  + ('' if responses_ok else ' 存在缺 id/usage 的回复'))
check(2, '独立 API 记录（佐证）', api_ok, api_detail)

# API 交付副本必须已脱敏，且保留响应 ID、usage、代码与测试证据
api_text = api_files[0].read_text(encoding='utf-8') if api_files else ''
api_json = json.loads(api_text) if api_files else {}
has_code = '```python' in api_text
has_tests = any(r.get('tests', {}).get('exit_code') is not None for r in api_json.get('rounds', []))
no_think = '<think>' not in api_text and '</think>' not in api_text
check(2, 'API 交付副本已脱敏且保留关键证据', no_think and has_code and has_tests and bool(api_json.get('_redaction')),
      f"无思维链标记={no_think} 保留代码块={has_code} 保留测试结果={has_tests} "
      f"脱敏说明={bool(api_json.get('_redaction'))}")

# ---------------------------------------------------------------- 辅助函数
def sha256_text(text):
    """文本按 LF 归一化后的 SHA-256（模型产出的代码本身就是 LF）。"""
    return hashlib.sha256(text.replace('\r\n', '\n').encode('utf-8')).hexdigest()


def run_delivered_tests(produced):
    """把交付的测试文件与归档产出的代码放在一起实跑一遍。

    这是与平台无关的证明：不依赖任何一台上机器算出来的哈希。
    """
    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary)
        shutil.copyfile(produced, work / 'task_service.py')
        shutil.copyfile(ROOT / 'sample' / 'test_task_service.py', work / 'test_task_service.py')
        env = dict(os.environ, PYTHONPATH=str(work))
        return subprocess.run([sys.executable, '-B', '-m', 'unittest', 'test_task_service'],
                              cwd=work, env=env, capture_output=True, text=True)


def context_of_run(run_dir):
    """取该次运行交给 MiniMax 的上下文：steps.json 里 context-before-change 步骤的输出。"""
    steps_path = run_dir / 'steps.json'
    if not steps_path.is_file():
        return None, '缺少 steps.json'
    try:
        steps = json.loads(steps_path.read_text(encoding='utf-8'))
    except ValueError as error:
        return None, f'steps.json 解析失败: {error}'
    for step in steps:
        if step.get('step') == 'context-before-change':
            try:
                return json.loads(step.get('stdout') or ''), None
            except ValueError as error:
                return None, f'context-before-change 输出解析失败: {error}'
    return None, 'steps.json 里没有 context-before-change 步骤'


def live_archive_problems(run_dir, summary, local_tests_raw, local_tests_lf):
    """逐份核对一份「声明成功且是实时调用」的归档，返回不一致之处。

    返回的每一条都带运行编号与具体位置，便于定位。
    """
    problems = []
    name = run_dir.name
    exchanges = sorted(run_dir.glob('*-exchange.json'))
    if not exchanges:
        return [f'{name}: 缺少 exchange 记录']
    exchange = json.loads(exchanges[0].read_text(encoding='utf-8'))
    rounds = exchange.get('rounds') or []
    if not rounds:
        return [f'{name}: exchange 的 rounds 为空']

    # 1) 每轮都要有响应 ID、usage；代码摘要分两种情况：
    #    「本轮没有产出代码」（摘要字段明确为 None）与「有代码但摘要缺失/不符」。
    for index, item in enumerate(rounds):
        number = item.get('round')
        is_last = index == len(rounds) - 1
        response = item.get('response') or {}
        if not response.get('id'):
            problems.append(f'{name}: 第 {number} 轮缺响应 ID')
        if not response.get('usage'):
            problems.append(f'{name}: 第 {number} 轮缺 usage')
        content = ''
        try:
            content = response['choices'][0]['message']['content'] or ''
        except (KeyError, IndexError, TypeError):
            content = ''
        code = None
        try:
            code = extract_code(content)
        except (NoCodeBlockError, KeyError, IndexError, TypeError):
            code = None
        if 'code_sha256' not in item:
            # 字段缺失不能冒充「显式的 None」
            problems.append(f'{name}: 第 {number} 轮缺 code_sha256 字段')
            continue
        recorded = item['code_sha256']
        if recorded is None:
            # 合法情况只有一种：本轮确实没有产出代码，且这一轮是失败的非末轮。
            if code is not None:
                problems.append(f'{name}: 第 {number} 轮回复里有代码，但 code_sha256 为 None')
            elif not content.strip():
                problems.append(f'{name}: 第 {number} 轮回复内容为空，不能当作「本轮没有产出代码」')
            elif is_last:
                problems.append(f'{name}: 末轮没有产出代码')
            else:
                exit_code = (item.get('tests') or {}).get('exit_code')
                if exit_code is None:
                    problems.append(f'{name}: 第 {number} 轮没有产出代码，也没有测试结果')
                elif exit_code == 0:
                    problems.append(f'{name}: 第 {number} 轮没有产出代码，测试却通过')
                elif not (item.get('tests') or {}).get('output'):
                    problems.append(f'{name}: 第 {number} 轮没有产出代码，且未保留失败信息')
            continue
        if not isinstance(recorded, str) or not SHA256_RE.fullmatch(recorded):
            problems.append(f'{name}: 第 {number} 轮的 code_sha256 不是有效的 SHA-256（{recorded!r}）')
            continue
        if code is None:
            problems.append(f'{name}: 第 {number} 轮记录了代码摘要，但回复里提取不出代码')
            continue
        actual = sha256_text(code)
        if actual != recorded:
            problems.append(f'{name}: 第 {number} 轮的 code_sha256 与回复中的代码不符'
                            f'（记录 {recorded[:16]}… / 复算 {actual[:16]}…）')

    # 2) 末轮必须测试通过
    last = rounds[-1]
    if (last.get('tests') or {}).get('exit_code') != 0:
        problems.append(f'{name}: 末轮测试未通过'
                        f'（exit_code={(last.get("tests") or {}).get("exit_code")}）')

    # 3) 产出文件必须在归档里
    produced = run_dir / 'task_service.py'
    if not produced.is_file():
        problems.append(f'{name}: 缺少产出文件 task_service.py')
        produced_sha_lf = ''
    else:
        produced_sha_lf = sha256_lf(produced)

    # 4) 末轮回复代码 / exchange 产出摘要 / 归档源码 / summary 产出摘要必须互相对应。
    #    两个摘要都是**必需字段**：先确认存在、类型正确、且是有效的 SHA-256，再比内容。
    try:
        last_sha = sha256_text(extract_code(last['response']['choices'][0]['message']['content']))
    except (NoCodeBlockError, KeyError, IndexError, TypeError):
        last_sha = ''
    exchange_after = exchange.get('after_sha256')
    if not isinstance(exchange_after, str) or not SHA256_RE.fullmatch(exchange_after or ''):
        problems.append(f'{name}: exchange.after_sha256 缺失或不是有效的 SHA-256'
                        f'（{exchange.get("after_sha256")!r}）')
        exchange_after = ''
    summary_after = summary.get('after_sha256')
    if not isinstance(summary_after, str) or not SHA256_RE.fullmatch(summary_after or ''):
        problems.append(f'{name}: summary.after_sha256 缺失或不是有效的 SHA-256'
                        f'（{summary.get("after_sha256")!r}）')
        summary_after = ''
    # 口径说明：exchange.after_sha256 与 summary.after_sha256 都是产出那台机器上的
    # 原始字节摘要（agent 以 newline='\n' 写文件，故为 LF）；归档源码在 Windows 检出后
    # 会被转成 CRLF，因此与归档源码比较时必须用 **LF 归一化**哈希，不混用两种口径。
    if last_sha and exchange_after and last_sha != exchange_after:
        problems.append(f'{name}: 末轮回复中的代码与 exchange.after_sha256 不符'
                        f'（{last_sha[:16]}… / {exchange_after[:16]}…）')
    if produced_sha_lf and exchange_after and produced_sha_lf != exchange_after:
        problems.append(f'{name}: 归档源码与 exchange.after_sha256 不符'
                        f'（LF 归一化 {produced_sha_lf[:16]}… / {exchange_after[:16]}…）')
    if summary_after and exchange_after and summary_after != exchange_after:
        problems.append(f'{name}: summary 的产出摘要与 exchange.after_sha256 不符'
                        f'（{summary_after[:16]}… / {exchange_after[:16]}…）')

    # 5) 首轮请求必须就是这次上下文构造出的提示
    ctx, error = context_of_run(run_dir)
    if ctx is None:
        problems.append(f'{name}: 取不到交给 MiniMax 的上下文（{error}）')
    else:
        try:
            expected = build_prompt(ctx)
        except Exception as error:                       # noqa: BLE001
            expected = None
            problems.append(f'{name}: 用该上下文构造提示失败（{error}）')
        if expected is not None:
            messages = (rounds[0].get('request') or {}).get('messages') or []
            actual = next((m.get('content', '') for m in reversed(messages)
                           if m.get('role') == 'user'), '')
            if actual != expected:
                problems.append(f'{name}: 首轮请求的任务提示与该次 context-before-change 不一致')

    # 6) 测试来源与测试摘要
    recorded_lf = summary.get('tests_sha256_lf')
    recorded_raw = summary.get('tests_sha256')
    if recorded_lf:
        same_tests = recorded_lf == local_tests_lf
    else:
        same_tests = recorded_raw in (local_tests_raw, local_tests_lf)
    if not same_tests:
        problems.append(f'{name}: 该次运行记录的测试文件哈希与交付的测试文件不一致'
                        f'（记录 {str(recorded_lf or recorded_raw)[:16]}… / 交付 '
                        f'{local_tests_lf[:16]}…）')
    steps_path = run_dir / 'steps.json'
    if steps_path.is_file():
        try:
            steps = json.loads(steps_path.read_text(encoding='utf-8'))
        except ValueError:
            steps = []
        by_step = {s.get('step'): s for s in steps}
        for step_name in ('tests-after-target', 'tests-after-regression'):
            if by_step.get(step_name, {}).get('exit_code') != 0:
                problems.append(f'{name}: 该次运行的 {step_name} 未通过'
                                f'（exit_code={by_step.get(step_name, {}).get("exit_code")}）')

    # 7) 对归档产出实跑交付的同一组业务测试
    if produced.is_file():
        run = run_delivered_tests(produced)
        if run.returncode != 0 or 'Ran 7 tests' not in run.stderr:
            last_line = (run.stderr.strip().splitlines() or [''])[-1]
            problems.append(f'{name}: 归档产出跑交付的同一组业务测试未通过（{last_line}）')
    return problems


# 实时调用归档：只挑选「声明成功且是实时调用」的归档，对这些**逐份**严格验证。
# 不能先过滤掉损坏的、再拿旧的成功记录顶替——那样损坏的成功归档会被静默放过。
live_archives, ordinary_archives, unreadable = [], [], []
for run_dir in sorted((ROOT / 'evidence' / 'run').glob('*/')):
    summary_path = run_dir / 'summary.json'
    if not summary_path.is_file():
        continue
    try:
        summary = json.loads(summary_path.read_text(encoding='utf-8'))
    except ValueError as error:
        unreadable.append(f'{run_dir.name}（{error}）')
        continue
    if summary.get('result') == 'PASS' and summary.get('minimax') == 'live':
        live_archives.append((run_dir, summary))
    else:
        ordinary_archives.append(run_dir.name)

check(2, '归档的 summary.json 均可解析', not unreadable,
      '全部归档的 summary.json 均可解析' if not unreadable
      else f'无法解析的归档：{unreadable}')

local_tests_raw = sha256(ROOT / 'sample' / 'test_task_service.py')
local_tests_lf = sha256_lf(ROOT / 'sample' / 'test_task_service.py')

archive_problems = []
for run_dir, summary in live_archives:
    archive_problems.extend(live_archive_problems(run_dir, summary, local_tests_raw, local_tests_lf))
check(2, '实时成功归档逐份材料自洽', bool(live_archives) and not archive_problems,
      f'共 {len(live_archives)} 份声明成功且为实时调用的归档（{sorted(d.name for d, _ in live_archives)}），'
      f'逐份核对通过；另有 {len(ordinary_archives)} 份非实时成功归档不参与本项判定'
      if live_archives and not archive_problems
      else (('不一致：' + '；'.join(archive_problems)) if archive_problems
            else '没有找到声明成功且为实时调用的归档'))


def record_time(run_dir):
    """归档的记录时间：取 exchange 里的 time_utc。"""
    for exchange in sorted(run_dir.glob('*-exchange.json')):
        try:
            record = json.loads(exchange.read_text(encoding='utf-8'))
        except ValueError:
            continue
        stamp = record.get('time_utc')
        if stamp:
            return stamp
    return ''


# 最新一次实时调用按**记录时间**选择，不按目录名字典序（字典序只是目录名的偶然顺序）
timed = sorted(((record_time(run_dir), run_dir.name) for run_dir, _ in live_archives))
check(2, '最新实时调用按记录时间选出', bool(timed),
      f'共 {len(live_archives)} 份实时成功归档；按 exchange 的 time_utc 排序，'
      f'最新的是 {timed[-1][1]}（{timed[-1][0]}）' if timed else '没有实时成功归档')

# 实时产出的代码**不要求**与交付快照 sample/after/task_service.py 逐字节相同。
# 结论只写「通过交付的同一组业务测试」，不据七个用例宣称所有输入下完全等价。
if timed:
    latest = next(run_dir for run_dir, _ in live_archives if run_dir.name == timed[-1][1])
    produced = latest / 'task_service.py'
    if produced.is_file():
        probe_run = run_delivered_tests(produced)
        ran_7 = 'Ran 7 tests' in probe_run.stderr
        last_line = (probe_run.stderr.strip().splitlines() or [''])[-1]
        check(2, '最新实时产出通过交付的同一组业务测试', probe_run.returncode == 0 and ran_7,
              f'把交付的 test_task_service.py 与归档产出放在一起实跑：{last_line}'
              f'（未要求与交付快照逐字节相同）')
    else:
        check(2, '最新实时产出通过交付的同一组业务测试', False,
              f'归档 {latest.name} 里没有产出文件')

# ------------------------------------------------------------- 3 上下文正确
initial = read_json('evidence/run/context-initial.json')
updated = read_json('evidence/run/context-updated.json')
roles = {e['role'] for e in initial['spec_entries']}
sources = {e['source'] for e in initial['spec_entries']}
targets = [t['source'] for t in initial['code_targets']]
func = initial['tests']['functional']
regr = initial['tests']['regression']
ok3 = (roles == {'implement', 'preserve'} and 'spec.md#TASK-2' in sources and 'spec.md#TASK-1' in sources
       and any('list_tasks' in t for t in targets) and len(func) == 5 and len(regr) == 2)
check(3, '输出定位规格/代码/测试来源', ok3,
      f"规格 {sorted(sources)}；代码 {targets}；功能测试 {len(func)} 项、回归测试 {len(regr)} 项")

# 规格更新后重新导入必须使用新内容
old_text = next(e['text'] for e in initial['spec_entries'] if e['role'] == 'implement')
new_text = next(e['text'] for e in updated['spec_entries'] if e['role'] == 'implement')
check(3, '规格更新后输出用新内容', new_text != old_text and len(new_text) > len(old_text),
      f'implement 条目正文由 {len(old_text)} 字增至 {len(new_text)} 字，追加内容已生效')

# ------------------------------------------------------- 4 数据库实际参与
queries = initial['query']['all_queries']
real = [q for q in queries if q.get('rows', 0) > 0 and q.get('sql', '').upper().startswith('SELECT')]
check(4, '查询结果进入上下文', len(real) >= 4 and all('sdd_' in q['sql'] for q in real),
      f'{len(queries)} 条查询，{len(real)} 条有返回行数，来源表 '
      f"{sorted({t for q in real for t in ['sdd_sources', 'sdd_entries'] if t in q['sql']})}")

# ------------------------------------------------------------- 5 状态能够复用
before = initial['progress']
after = read_json('evidence/run/context-restored.json')['progress']
ok5 = (before.get('completed') == [] and before.get('todo') == [] and before.get('verification') == []
       and after.get('completed') and after.get('verification'))
check(5, '空状态写入、重启后读回并使用', ok5,
      f'初始 progress 全空；重启后 completed {len(after.get("completed", []))} 项、'
      f'verification {len(after.get("verification", []))} 组，来源 {after.get("source")}')

# ------------------------------------------------------------- 6 代码修改有效
by_step = {s['step']: s for s in steps}
bt = by_step.get('tests-before-target', {})
br = by_step.get('tests-before-regression', {})
at = by_step.get('tests-after-target', {})
ar = by_step.get('tests-after-regression', {})
verdict = (bt.get('stderr', '').strip().splitlines() or [''])[-1]
ok6 = (bt.get('exit_code') == 1 and 'failures=' in verdict and 'errors=' not in verdict
       and br.get('exit_code') == 0 and at.get('exit_code') == 0 and ar.get('exit_code') == 0)
check(6, '同组测试修改前失败、修改后全通过', ok6,
      f'修改前 功能={bt.get("exit_code")}({verdict}) 回归={br.get("exit_code")}；'
      f'修改后 功能={at.get("exit_code")} 回归={ar.get("exit_code")}')

# 测试集前后一致
tests_sha = sha256(ROOT / 'sample' / 'test_task_service.py')
# 测试集前后一致：优先比「LF 归一化」哈希——Windows 工作区是 CRLF、Linux 是 LF，
# 记录的原始摘要是产出它那台机器上的字节，跨平台只有归一化形式才可比。
tests_sha_raw = sha256(ROOT / 'sample' / 'test_task_service.py')
tests_sha_lf = sha256_lf(ROOT / 'sample' / 'test_task_service.py')
recorded_lf = run.get('tests_sha256_lf')
recorded_raw = run.get('tests_sha256')
if recorded_lf:
    same_test_set = recorded_lf == tests_sha_lf
    detail = f'归一化哈希一致（recorded {recorded_lf[:16]}… == 本地 {tests_sha_lf[:16]}…）'
else:
    same_test_set = recorded_raw in (tests_sha_raw, tests_sha_lf)
    detail = f'原始哈希一致={recorded_raw in (tests_sha_raw, tests_sha_lf)}'
check(6, '测试集前后一致', same_test_set,
      f'sample/test_task_service.py {detail}')

# ------------------------------------------------------------------ 汇总输出
print('=' * 78)
print('官方六项必做项 · 交付材料一致性自检')
print('=' * 78)
current = None
for item, name, ok, detail in results:
    if item != current:
        print(f'\n【{item}】')
        current = item
    print(f'  [{"PASS" if ok else "FAIL"}] {name}')
    print(f'         {detail}')
failed = [r for r in results if not r[2]]
print('\n' + '=' * 78)
print(f'共 {len(results)} 项检查，通过 {len(results) - len(failed)}，失败 {len(failed)}')
if failed:
    print('未通过：')
    for item, name, _, detail in failed:
        print(f'  - [{item}] {name}: {detail}')
    sys.exit(1)
print('全部通过。')
print('说明：这是交付材料一致性自检，不能认证模型服务商来源，也不代替官方验收；')
print('      官方评分以平台记录的固定提交为准。')
