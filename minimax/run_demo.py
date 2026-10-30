"""完整验证样例：导入 → 上下文 → MiniMax 修改 → 测试 → 状态保存 → 重启复用 → 规格更新。

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

import pymysql

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'evidence' / 'run'
TARGET_TESTS = ['FeatureTests']          # 目标功能测试（修改前必须失败）
REGRESSION_TESTS = ['RegressionTests']   # 原有行为回归测试（修改前后都必须通过）
steps = []


def probe_database(host, port, user, password):
    try:
        pymysql.connect(host=host, port=port, user=user, password=password, connect_timeout=3).close()
        return True
    except Exception:
        return False


def probe_powercontext(opener, pc_url):
    """只认预期的正常响应：200。

    任何 HTTP 错误（含 503）与连接失败都算未就绪——服务真的没起来时不能误判为就绪。
    """
    try:
        with opener.open(pc_url + '/openapi.json', timeout=3) as response:
            return response.status == 200
    except Exception:
        return False


def wait_for_services(timeout, db_probe=None, pc_probe=None, interval=2):
    """等待 seekdb 与 PowerContext 就绪，返回仍未就绪的服务名列表。

    seekdb 冷启动需要数秒到数十秒（容器内更久），刚起就连接会失败，
    因此在正式步骤前先等待，避免评审按 README 顺序执行时第一步就报错。
    """
    host = os.getenv('DB_HOST', '127.0.0.1')
    port = int(os.getenv('DB_PORT', '18753'))
    pc_url = os.getenv('PC_URL', 'http://127.0.0.1:18752').rstrip('/')
    # 本机服务必须直连，不能走环境里的 HTTP 代理
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    db_probe = db_probe or (lambda: probe_database(host, port, os.getenv('DB_USER', 'root'),
                                                   os.getenv('DB_PASSWORD', '')))
    pc_probe = pc_probe or (lambda: probe_powercontext(opener, pc_url))
    pending = {'seekdb': True, 'PowerContext': True}
    deadline = time.time() + timeout
    while any(pending.values()) and time.time() < deadline:
        if pending['seekdb'] and db_probe():
            pending['seekdb'] = False
        if pending['PowerContext'] and pc_probe():
            pending['PowerContext'] = False
        if any(pending.values()):
            time.sleep(interval)
    return [name for name, waiting in pending.items() if waiting]


def git_revision():
    try:
        return subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], capture_output=True,
                              text=True).stdout.strip() or None
    except OSError:
        return None


def step(name, command, env=None, expect=0, parse=True, code_sha256=None, tests_sha256=None):
    run = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                         env=dict(os.environ, PYTHONIOENCODING='utf-8', **(env or {})))
    record = {'step': name, 'command': command, 'exit_code': run.returncode,
              'stdout': run.stdout, 'stderr': run.stderr}
    # 测试日志要能看出「这一步跑的是哪版代码、哪份测试」——
    # 官方「四、评分与测试」要求：测试日志需记录命令、退出码和对应代码版本。
    if code_sha256:
        record['code_sha256'] = code_sha256
    if tests_sha256:
        record['tests_sha256'] = tests_sha256
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


def sha256_lf(path):
    """按 LF 归一化后的哈希：跨平台（Windows CRLF / Linux LF）可比。"""
    return hashlib.sha256(Path(path).read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--recorded', action='store_true', help='使用已记录的 MiniMax 输出，不调用 API')
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex[:12]
    # 本次运行的证据按运行编号单独存放；OUT 根目录只保留「最近一次成功运行」的固定文件。
    run_dir = OUT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    project, task = f'taskboard-{run_id}', 'TASK-2'
    py = [sys.executable, str(ROOT / 'context.py')]
    summary = {'run_id': run_id, 'git_revision': git_revision(), 'project': project, 'task': task,
               'minimax': 'recorded' if args.recorded else 'live'}
    passed = False
    try:
        with tempfile.TemporaryDirectory() as temporary:
            # 独立副本：规格更新、MiniMax 输出都写在副本中，仓库原始样例不变
            sample = Path(temporary) / 'sample'
            shutil.copytree(ROOT / 'sample', sample, ignore=shutil.ignore_patterns('__pycache__'))
            manifest = sample / 'manifest.json'
            work = sample / 'work'
            work.mkdir()
            shutil.copy(sample / 'before' / 'task_service.py', work / 'task_service.py')

            # 0. 等待 seekdb 与 PowerContext 就绪
            waiting = wait_for_services(int(os.getenv('DEMO_WAIT_TIMEOUT', '180')))
            steps.append({'step': 'wait-services',
                          'command': ['(internal)', 'wait for seekdb and PowerContext'],
                          'exit_code': 1 if waiting else 0,
                          'stdout': '' if not waiting else f'仍未就绪: {waiting}', 'stderr': ''})
            print(f'[{"1" if waiting else "0"}] wait-services', flush=True)
            if waiting:
                raise SystemExit(f'服务未就绪：{waiting}')

            # 1. 导入资料到 seekdb
            summary['ingest'] = step('ingest', [*py, 'ingest', '--project', project, '--manifest', str(manifest)])
            # 2. PowerContext：新 scope，从空状态开始保存任务记录
            scope_id = step('scope', [*py, 'scope', '--key', f'minimax-demo-{run_id}'])['scope_id']
            summary['scope_id'] = scope_id
            ctx_args = [*py, 'context', '--project', project, '--task', task, '--scope', scope_id]
            initial = step('context-initial', ctx_args)
            assert initial['progress']['completed'] == [], '新 scope 应为空状态'
            start = Path(temporary) / 'state-start.json'
            start.write_text(json.dumps({'task': task, 'completed': ['导入规格、代码与测试到 seekdb'],
                                         'todo': ['由 MiniMax 依据上下文修改代码', '运行功能与回归测试'],
                                         'tests': []}, ensure_ascii=False), encoding='utf-8')
            step('save-start', [*py, 'save', '--scope', scope_id, '--state', str(start)])

            # 3. 修改前：目标功能测试失败（目标行为未实现），回归测试通过
            #    先记下这一版代码与这份测试的哈希，测试步骤一并写进步骤日志
            before_sha = sha(work / 'task_service.py')
            tests_sha = sha(sample / 'test_task_service.py')
            command, env = unittest(work, sample, TARGET_TESTS)
            before_target = step('tests-before-target', command, env, expect=1, parse=False,
                                 code_sha256=before_sha, tests_sha256=tests_sha)
            command, env = unittest(work, sample, REGRESSION_TESTS)
            step('tests-before-regression', command, env, expect=0, parse=False,
                 code_sha256=before_sha, tests_sha256=tests_sha)
            # 修改前的失败必须是断言失败（行为未实现），不能是导入错误等环境问题
            verdict = before_target['stderr'].strip().splitlines()[-1]
            assert 'failures=' in verdict and 'errors=' not in verdict, verdict

            # 4. 重启后的上下文读取已保存的状态，再交给 MiniMax
            resumed = step('context-before-change', ctx_args)
            assert resumed['progress']['todo'], '重启后应读到已保存的待办'
            if args.recorded:
                shutil.copy(sample / 'after' / 'task_service.py', work / 'task_service.py')
                step('minimax-recorded', [sys.executable, '-c', 'print("使用仓库中已记录的 MiniMax 输出")'], parse=False)
            else:
                step('minimax', [sys.executable, str(ROOT / 'minimax_agent.py'), '--project', project,
                                 '--task', task, '--scope', scope_id, '--output', str(work / 'task_service.py'),
                                 '--evidence-dir', str(run_dir)])
                # 只把本次产出存进本次运行的证据目录，不覆盖交付的固定业务快照 sample/after/
                shutil.copyfile(work / 'task_service.py', run_dir / 'task_service.py')
            after_sha = sha(work / 'task_service.py')

            # 5. 修改后：同一组目标测试与回归测试全部通过
            command, env = unittest(work, sample, TARGET_TESTS)
            step('tests-after-target', command, env, expect=0, parse=False,
                 code_sha256=after_sha, tests_sha256=tests_sha)
            command, env = unittest(work, sample, REGRESSION_TESTS)
            step('tests-after-regression', command, env, expect=0, parse=False,
                 code_sha256=after_sha, tests_sha256=tests_sha)

            # 6. 保存验证结果；重启后的上下文使用这些结果
            done = Path(temporary) / 'state-done.json'
            done.write_text(json.dumps({'task': task,
                'completed': ['导入规格、代码与测试到 seekdb', 'MiniMax 依据上下文完成代码修改', '功能测试与回归测试通过'],
                'todo': [],
                'tests': [{'stage': 'before', 'target_exit': 1, 'regression_exit': 0, 'code_sha256': before_sha},
                          {'stage': 'after', 'target_exit': 0, 'regression_exit': 0, 'code_sha256': after_sha,
                           'tests_sha256': tests_sha}]}, ensure_ascii=False), encoding='utf-8')
            step('save-done', [*py, 'save', '--scope', scope_id, '--state', str(done)])
            restored = step('context-restored', ctx_args)
            assert restored['progress']['todo'] == [] and len(restored['progress']['verification']) == 2

            # 7. 规格更新并重新导入后，上下文使用新内容
            marker = f'更新标记 {run_id}：status 参数也接受 None 以外的空白字符串时报错'
            with (sample / 'spec.md').open('a', encoding='utf-8') as stream:
                stream.write(f'\n## TASK-2 规格补充\n{marker}\n')
            step('ingest-updated', [*py, 'ingest', '--project', project, '--manifest', str(manifest)])
            updated = step('context-updated', ctx_args)
            target = next(e for e in updated['spec_entries'] if e['role'] == 'implement')
            assert marker in target['text'], '重新导入后应返回更新的规格'

            for name, value in (('context-initial', initial), ('context-restored', restored),
                                ('context-updated', updated)):
                (run_dir / f'{name}.json').write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
            summary.update({'before_sha256': before_sha, 'after_sha256': after_sha, 'tests_sha256': tests_sha,
                            # 同时记录按 LF 归一化后的哈希：Windows 工作区是 CRLF、Linux 是 LF，
                            # 跨平台比对摘要时只有归一化形式才可比。
                            'tests_sha256_lf': sha256_lf(sample / 'test_task_service.py'),
                            'result': 'PASS'})
            passed = True
            print('PASS')
    except Exception as error:
        summary['error'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        if not passed:
            summary['result'] = 'FAIL'
        # 本次运行的证据始终写入自己的目录；失败也不会破坏已有成功证据
        (run_dir / 'steps.json').write_text(json.dumps(steps, ensure_ascii=False, indent=2), encoding='utf-8')
        (run_dir / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        if passed:
            # 只有成功才刷新「最近一次成功运行」的固定文件
            for name in ('steps.json', 'summary.json', 'context-initial.json',
                         'context-restored.json', 'context-updated.json'):
                shutil.copyfile(run_dir / name, OUT / name)


if __name__ == '__main__':
    main()
