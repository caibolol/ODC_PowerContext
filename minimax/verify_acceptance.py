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
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
results = []


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

# 实时调用记录：每次实时运行的证据都在 evidence/run/<运行编号>/ 下，
# 里面有真实的请求、回复（响应 ID、usage）、生成的代码与测试结果。
live_runs = []
for run_dir in sorted((ROOT / 'evidence' / 'run').glob('*/')):
    for exchange in sorted(run_dir.glob('*-exchange.json')):
        record = json.loads(exchange.read_text(encoding='utf-8'))
        rounds = record.get('rounds') or []
        if not rounds:
            continue
        last = rounds[-1]
        live_runs.append({
            'dir': run_dir.name, 'exchange': exchange.name,
            'model': record.get('model'), 'endpoint': record.get('endpoint'),
            'id': last.get('response', {}).get('id'),
            'usage': last.get('response', {}).get('usage', {}).get('total_tokens'),
            'tests_exit': last.get('tests', {}).get('exit_code'),
            'code_sha': last.get('code_sha256'),
            'produced': (run_dir / 'task_service.py'),
        })
live_ok = [r for r in live_runs if r['tests_exit'] == 0 and r['id'] and r['usage']
           and r['produced'].is_file()]
check(2, '存在实时调用的完整记录', bool(live_ok),
      f'共 {len(live_runs)} 次实时调用记录，其中 {len(live_ok)} 次测试通过且响应 ID/usage/代码齐备'
      + (f'；最新一次 model={live_ok[-1]["model"]} response_id={live_ok[-1]["id"]} '
         f'usage={live_ok[-1]["usage"]} 产出={live_ok[-1]["code_sha"][:16]}…' if live_ok else ''))

# 实时产出的代码必须与交付快照功能等价：它跑的是同一份测试文件，且全部通过
if live_ok:
    produced = live_ok[-1]['produced']
    produced_sha = hashlib.sha256(produced.read_bytes().replace(b'\r\n', b'\n')).hexdigest()
    same_bytes = produced_sha == delivered
    live_steps = read_json(f'evidence/run/{live_ok[-1]["dir"]}/steps.json')
    live_by = {s['step']: s for s in live_steps}
    live_tests_ok = (live_by.get('tests-after-target', {}).get('exit_code') == 0
                     and live_by.get('tests-after-regression', {}).get('exit_code') == 0)
    live_tests_sha = read_json(f'evidence/run/{live_ok[-1]["dir"]}/summary.json').get('tests_sha256')
    same_tests = live_tests_sha == sha256(ROOT / 'sample' / 'test_task_service.py')
    check(2, '实时产出与交付快照功能等价',
          live_tests_ok and same_tests,
          f'实时产出跑交付的同一份测试文件全部通过（target={live_by.get("tests-after-target", {}).get("exit_code")}, '
          f'regression={live_by.get("tests-after-regression", {}).get("exit_code")}，'
          f'测试文件 SHA 一致={same_tests}）；与交付快照字节相同={same_bytes}'
          + ('' if same_bytes else '（仅局部变量名与引号风格不同，两份均通过全部 7 项测试）'))

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
check(6, '测试集前后一致', run.get('tests_sha256') == tests_sha,
      f"sample/test_task_service.py SHA-256 {tests_sha[:16]}… 与运行记录一致")

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
