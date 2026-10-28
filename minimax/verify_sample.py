"""使用完全相同的测试验证修改前后的代码，并保留命令、版本和退出码。"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
evidence = ROOT / 'evidence'
evidence.mkdir(exist_ok=True)
results = []
for stage in ('before', 'after'):
    source = ROOT / 'sample' / stage / 'task_service.py'
    if not source.exists():
        raise SystemExit(f'缺少实际代码：{source}')
    env = dict(os.environ, PYTHONPATH=str(source.parent))
    command = [sys.executable, '-B', '-m', 'unittest', 'discover',
               '-s', str(ROOT / 'sample'), '-p', 'test_task_service.py', '-v']
    run = subprocess.run(command, env=env, capture_output=True, text=True)
    result = {'stage': stage, 'command': command, 'exit_code': run.returncode,
              'code_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'tests_sha256': hashlib.sha256((ROOT / 'sample/test_task_service.py').read_bytes()).hexdigest(),
              'stdout': run.stdout, 'stderr': run.stderr}
    results.append(result)
(evidence / 'tests.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps([{'stage': r['stage'], 'exit_code': r['exit_code']} for r in results]))
assert results[0]['exit_code'] == 1 and results[1]['exit_code'] == 0
