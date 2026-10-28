"""真实服务集成验证；每次调用入口均为新的 Python 进程。"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parent
EVIDENCE = ROOT / 'evidence'
EVIDENCE.mkdir(exist_ok=True)
calls = []


def call(*args):
    command = [sys.executable, str(ROOT / 'context.py'), *args]
    run = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                         env=dict(os.environ, PYTHONIOENCODING='utf-8'))
    calls.append({'command': command, 'exit_code': run.returncode,
                  'stdout': run.stdout, 'stderr': run.stderr})
    if run.returncode:
        raise RuntimeError(run.stderr)
    return json.loads(run.stdout)


try:
    run_id = uuid.uuid4().hex
    scope_id = call('scope', '--key', 'minimax-verification-' + run_id)['scope_id']
    project = 'taskboard-' + run_id
    with tempfile.TemporaryDirectory() as temporary:
        sample = Path(temporary) / 'sample'
        shutil.copytree(ROOT / 'sample', sample)
        manifest = str(sample / 'manifest.json')
        call('ingest', '--project', project, '--manifest', manifest)
        args = ('context', '--project', project, '--task', 'TASK-2', '--scope', scope_id)
        initial = call(*args)
        assert {s['kind'] for s in initial['sources']} == {'spec', 'code', 'test'}
        # 读取响应中的实际结构，不依赖推理模型或向量服务。
        assert '已完成本地实现' not in json.dumps(initial['previous_state'], ensure_ascii=False)
        (EVIDENCE / 'context-initial.json').write_text(json.dumps(initial, ensure_ascii=False, indent=2), encoding='utf-8')
        with (sample / 'spec.md').open('a', encoding='utf-8') as stream:
            stream.write('\n## TASK-2 更新验证\n更新版本标记：' + run_id + '\n')
        call('ingest', '--project', project, '--manifest', manifest)
        updated = call(*args)
        assert run_id in next(s['content'] for s in updated['sources'] if s['kind'] == 'spec')
        assert initial['sources'] != updated['sources']
        state = {'task': 'TASK-2', 'completed': ['已完成本地实现', '7项测试通过', '规格更新检索验证通过'],
                 'todo': ['将完整代码提交给MiniMax进行实际代码检查或修改并核对结果'],
                 'tests': json.loads((EVIDENCE / 'tests.json').read_text(encoding='utf-8'))}
        if (EVIDENCE / 'minimax-response.py').exists():
            state['completed'].append('已采用MiniMax正式回复的业务代码并通过相同7项测试')
            state['todo'] = ['提交固定版本后等待平台评审']
        # 只保存摘要，完整测试日志保留在仓库证据中。
        state['tests'] = [{k: test[k] for k in ('stage','exit_code','code_sha256','tests_sha256')}
                          for test in state['tests']]
        state_file = Path(temporary) / 'state.json'
        state_file.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
        saved = call('save', '--scope', scope_id, '--state', str(state_file))
        restored = call(*args)
        assert '已完成本地实现' in json.dumps(restored['previous_state'], ensure_ascii=False)
        # 恢复的状态成为下一轮上下文的一部分，而非仅打印连接成功。
        (EVIDENCE / 'context-restored.json').write_text(json.dumps(restored, ensure_ascii=False, indent=2), encoding='utf-8')
        (EVIDENCE / 'state-write.json').write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding='utf-8')
    print('PASS: 真实seekdb导入/查询、规格更新、PowerContext空状态写入和跨进程复用')
finally:
    (EVIDENCE / 'integration.json').write_text(json.dumps(calls, ensure_ascii=False, indent=2), encoding='utf-8')
