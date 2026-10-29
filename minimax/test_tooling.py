"""工具自身的自检：输出校验、测试执行隔离、修复循环、验收脚本的负例。

用法（在 minimax/ 目录下）：
    python test_tooling.py

只用到标准库与被测模块，不连接数据库、不需要 PowerContext 在跑。
模型调用用**模拟**（替换 minimax_agent.call_minimax）；run_tests、子进程里的
unittest 执行、证据写入全部是真实的，不做模拟。
模拟产生的记录只留在临时测试目录里，不会进入交付材料。
"""
import http.server
import hashlib
import json
import os
import py_compile
import re
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import minimax_agent  # noqa: E402
import run_demo  # noqa: E402

OLD_CODE = 'def list_tasks(tasks, status=None):\n    return list(tasks)\n'
NEW_CODE = ('def list_tasks(tasks, status=None):\n'
            '    if status is None:\n'
            '        return list(tasks)\n'
            '    wanted = status.strip().casefold()\n'
            '    if wanted not in (\'todo\', \'done\'):\n'
            '        raise ValueError("status must be either \'todo\' or \'done\'")\n'
            '    return [t for t in tasks if t.get(\'status\', \'todo\').casefold() == wanted]\n')
# 与 NEW_CODE **字节数完全相同**的行为错误实现：只把 == 改成 !=
WRONG_CODE = NEW_CODE.replace('== wanted', '!= wanted')
BROKEN_SYNTAX = 'def list_tasks(tasks, status=None)\n    return list(tasks)\n'
TEST_SOURCE = ('import unittest\n'
               'from task_service import list_tasks\n\n\n'
               'class FeatureTests(unittest.TestCase):\n'
               '    def test_filter(self):\n'
               '        rows=[{"id":1,"status":"DONE"},{"id":2,"status":"TODO"}]\n'
               '        self.assertEqual(list_tasks(rows,"done"),[{"id":1,"status":"DONE"}])\n\n\n'
               'class RegressionTests(unittest.TestCase):\n'
               '    def test_no_filter(self):\n'
               '        self.assertEqual(list_tasks([{"id":1}]),[{"id":1}])\n')


def fake_ctx():
    """一份最小但结构完整的上下文（与 context.py 的输出同形）。"""
    return {
        'project': 'p', 'task': 'TASK-2',
        'code_targets': [{'path': 'before/task_service.py', 'symbol': 'list_tasks',
                          'type': 'FunctionDef', 'lines': [1, 2], 'source': 'before/task_service.py'}],
        'sources': [{'path': 'before/task_service.py', 'kind': 'code', 'content': OLD_CODE},
                    {'path': 'test_task_service.py', 'kind': 'test', 'content': TEST_SOURCE}],
        'tests': {'functional': ['test_task_service.py#FeatureTests.test_filter'],
                  'regression': ['test_task_service.py#RegressionTests.test_no_filter']},
        'progress': {'completed': [], 'todo': [], 'verification': []},
        'query': {'all_queries': [{'sql': 'SELECT 1', 'rows': 1}]},
        'spec_entries': [{'role': 'implement', 'entry_id': 'TASK-2', 'source': 'spec.md',
                          'lines': [1, 2], 'title': 't', 'text': 'text'}],
    }


def fake_reply(code, rid='resp-1'):
    return {'id': rid, 'model': 'MiniMax-M3', 'usage': {'total_tokens': 100},
            'choices': [{'message': {'content': '```python\n' + code + '```'}}]}


class OutputGuardTests(unittest.TestCase):
    """生成前与生成后的校验必须分开：生成前文件还不存在。"""

    def test_pre_generation_allows_missing_file(self):
        """生成前：文件名对即可，文件尚不存在不能算错误。"""
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'task_service.py'
            self.assertFalse(output.exists())
            self.assertEqual(minimax_agent.check_output_name(fake_ctx(), output), 'task_service')

    def test_pre_generation_rejects_mismatched_filename(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(SystemExit):
                minimax_agent.check_output_name(fake_ctx(), Path(temporary) / 'result.py')

    def test_post_generation_rejects_missing_file(self):
        """生成后：文件必须真实存在。"""
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(SystemExit):
                minimax_agent.check_output_exists(fake_ctx(), Path(temporary) / 'task_service.py')

    def test_post_generation_rejects_mismatched_filename(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'result.py'
            output.write_text(NEW_CODE, encoding='utf-8')
            with self.assertRaises(SystemExit):
                minimax_agent.check_output_exists(fake_ctx(), output)

    def test_post_generation_accepts_existing_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'task_service.py'
            output.write_text(NEW_CODE, encoding='utf-8')
            self.assertEqual(minimax_agent.check_output_exists(fake_ctx(), output), 'task_service')

    def test_tests_actually_run_the_output_file(self):
        """输出文件内容是未实现行为的旧代码时，测试必须失败——说明确实测的是该文件。"""
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'task_service.py'
            output.write_text(OLD_CODE, encoding='utf-8')
            result = minimax_agent.run_tests(fake_ctx(), output)
            self.assertNotEqual(result['exit_code'], 0)

    def test_tests_pass_on_implemented_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'task_service.py'
            output.write_text(NEW_CODE, encoding='utf-8')
            result = minimax_agent.run_tests(fake_ctx(), output)
            self.assertEqual(result['exit_code'], 0)


class StaleBytecodeTests(unittest.TestCase):
    """旧字节码不得污染新一轮的测试结果。

    Python 的字节码缓存以「源码 mtime（秒级）+ 字节数」校验，
    同样字节数、同样 mtime 秒值的错误源码会命中上一轮留下的 .pyc。
    """

    def seed_stale_cache(self, output, correct_code):
        """显式预先生成正确旧代码的 .pyc，并返回编译时记录的 mtime 秒值。

        这里显式调用 py_compile，不依赖外部「禁写缓存」的环境变量——
        那种变量在本机是开着的，会把问题掩盖掉。
        """
        output.write_text(correct_code, encoding='utf-8', newline='\n')
        py_compile.compile(str(output), doraise=True)
        pycs = list(output.parent.rglob('*.pyc'))
        self.assertTrue(pycs, '预置的 .pyc 没有生成')
        return int(output.stat().st_mtime)

    def test_stale_pyc_cannot_make_wrong_code_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'task_service.py'
            stamp = self.seed_stale_cache(output, NEW_CODE)
            # 换成**同样字节数**的错误代码，并把 mtime 秒值设回编译时的值
            output.write_text(WRONG_CODE, encoding='utf-8', newline='\n')
            os.utime(output, (stamp, stamp))
            self.assertEqual(output.stat().st_size,
                             len(NEW_CODE.encode()), '反例前提失效：字节数必须相同')
            result = minimax_agent.run_tests(fake_ctx(), output)
            self.assertNotEqual(result['exit_code'], 0,
                                '错误源码因为上一轮的 .pyc 被判为通过 —— 字节码污染')

    def test_correct_code_still_passes_with_stale_cache_present(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'task_service.py'
            stamp = self.seed_stale_cache(output, NEW_CODE)
            output.write_text(NEW_CODE, encoding='utf-8', newline='\n')
            os.utime(output, (stamp, stamp))
            result = minimax_agent.run_tests(fake_ctx(), output)
            self.assertEqual(result['exit_code'], 0)


class AgentFlowTests(unittest.TestCase):
    """走真实 main 流程：只模拟模型调用，其余（测试执行、证据写入）都是真实的。"""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.work = Path(self.temporary.name)
        self.ctx_path = self.work / 'ctx.json'
        self.ctx_path.write_text(json.dumps(fake_ctx(), ensure_ascii=False), encoding='utf-8')
        self.evidence = self.work / 'ev'
        self.calls = []

    def fake_call(self, messages, model, base_url, key):
        self.calls.append(messages)
        code = self.outputs[min(len(self.calls) - 1, len(self.outputs) - 1)]
        return ({'model': model, 'messages': messages},
                fake_reply(code, f'resp-{len(self.calls)}'), 0.01)

    def run_agent(self, outputs, output_name='task_service.py'):
        """在真实 main 里跑一轮，返回 (退出异常或 None, exchange 记录)。"""
        self.outputs = outputs
        out = self.work / 'fresh' / output_name
        out.parent.mkdir(exist_ok=True)
        original_call, original_argv = minimax_agent.call_minimax, sys.argv
        original_key = os.environ.get('MINIMAX_API_KEY')
        minimax_agent.call_minimax = self.fake_call
        sys.argv = ['minimax_agent.py', '--context-file', str(self.ctx_path), '--output', str(out),
                    '--evidence-dir', str(self.evidence)]
        os.environ['MINIMAX_API_KEY'] = 'dummy'
        try:
            minimax_agent.main()
            error = None
        except SystemExit as exit_error:
            error = str(exit_error)
        finally:
            minimax_agent.call_minimax, sys.argv = original_call, original_argv
            if original_key is None:
                os.environ.pop('MINIMAX_API_KEY', None)
            else:
                os.environ['MINIMAX_API_KEY'] = original_key
        exchanges = sorted(self.evidence.glob('*-exchange.json')) if self.evidence.exists() else []
        record = json.loads(exchanges[0].read_text(encoding='utf-8')) if exchanges else None
        return error, record

    def test_generates_into_fresh_directory_where_output_does_not_exist(self):
        """全新目录下 task_service.py 尚不存在：生成、测试、证据保存都要走通。"""
        error, record = self.run_agent([NEW_CODE])
        self.assertIsNone(error, f'main 意外退出：{error}')
        self.assertEqual(len(self.calls), 1, '模型应被调用一次')
        self.assertIsNotNone(record, 'exchange 记录未写出')
        self.assertEqual(record['rounds'][-1]['tests']['exit_code'], 0)

    def test_rejects_mismatched_filename_without_touching_neighbouring_module(self):
        """文件名不匹配必须明确拒绝，且不能误测旁边已有的 task_service.py。"""
        neighbour = self.work / 'fresh' / 'task_service.py'
        neighbour.parent.mkdir(exist_ok=True)
        neighbour.write_text(OLD_CODE, encoding='utf-8')
        error, record = self.run_agent([NEW_CODE], output_name='result.py')
        self.assertIsNotNone(error, '文件名不匹配时必须失败')
        self.assertIn('不一致', error)
        self.assertEqual(len(self.calls), 0, '拒绝必须发生在调用模型之前')
        self.assertIsNone(record, '被拒绝的运行不应留下 exchange')
        self.assertEqual(neighbour.read_text(encoding='utf-8'), OLD_CODE,
                         '旁边的同名模块不应被改动')

    def test_syntax_error_feeds_back_and_second_round_succeeds(self):
        """第一轮语法错误：应作为测试失败交回模型，第二轮正确代码后成功。"""
        error, record = self.run_agent([BROKEN_SYNTAX, NEW_CODE])
        self.assertIsNone(error, f'main 意外退出：{error}')
        self.assertEqual(len(self.calls), 2, '应实际调用两轮')
        self.assertIsNotNone(record)
        self.assertEqual(len(record['rounds']), 2, 'exchange 应保留两轮')
        first, second = record['rounds']
        self.assertEqual(first['tests']['exit_code'], 1, '第一轮应是测试失败')
        self.assertIn('SyntaxError', first['tests']['output'])
        self.assertEqual(second['tests']['exit_code'], 0)
        # 第二轮请求必须带上第一轮的失败信息
        second_text = ' '.join(m.get('content', '') for m in second['request']['messages'])
        self.assertIn('SyntaxError', second_text, '第二轮请求应包含第一轮的失败输出')
        # 两轮都要留下请求、回复、测试输出与退出码
        for item in record['rounds']:
            self.assertIn('request', item)
            self.assertIn('response', item)
            self.assertIn('exit_code', item['tests'])
            self.assertTrue(item['tests']['output'])
            self.assertTrue(item['response'].get('id'))
            self.assertTrue(item['response'].get('usage'))

    def test_all_rounds_failing_exits_nonzero_but_keeps_records(self):
        """所有轮次都失败：最终非零退出，已收到的轮次记录必须保留。"""
        error, record = self.run_agent([BROKEN_SYNTAX])
        self.assertIsNotNone(error, '全部轮次失败时必须非零退出')
        self.assertIsNotNone(record, '失败运行的轮次记录必须保留')
        self.assertEqual(len(record['rounds']), 3, '默认最多 3 轮，三轮记录都应保留')
        self.assertTrue(all(r['tests']['exit_code'] != 0 for r in record['rounds']))


class _StatusHandler(http.server.BaseHTTPRequestHandler):
    """按 self.server.fail_times 决定返回 503 还是 200。"""

    def do_GET(self):
        if self.server.fail_times > 0:
            self.server.fail_times -= 1
            self.send_response(503)
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        body = b'{}'
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class _Server(socketserver.TCPServer):
    allow_reuse_address = True


class ReadinessTests(unittest.TestCase):
    """就绪探测：503 不能被当成已就绪。"""

    def start_server(self, fail_times):
        server = _Server(('127.0.0.1', 0), _StatusHandler)
        server.fail_times = fail_times
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        # addCleanup 是后进先出：先注册 server_close，再注册 shutdown，保证先停服务再关套接字
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server, f'http://127.0.0.1:{server.server_address[1]}'

    def test_probe_rejects_503(self):
        server, url = self.start_server(fail_times=99)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.assertFalse(run_demo.probe_powercontext(opener, url))

    def test_probe_accepts_200(self):
        server, url = self.start_server(fail_times=0)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.assertTrue(run_demo.probe_powercontext(opener, url))

    def test_wait_succeeds_after_transient_503(self):
        """先返回 503、后正常：应等到正常响应再判定就绪。"""
        server, url = self.start_server(fail_times=2)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        waiting = run_demo.wait_for_services(
            timeout=20, db_probe=lambda: True,
            pc_probe=lambda: run_demo.probe_powercontext(opener, url), interval=1)
        self.assertEqual(waiting, [])

    def test_wait_fails_on_persistent_503(self):
        """持续 503：等待到超时后必须明确报未就绪，不能当成已就绪。"""
        server, url = self.start_server(fail_times=9999)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        waiting = run_demo.wait_for_services(
            timeout=4, db_probe=lambda: True,
            pc_probe=lambda: run_demo.probe_powercontext(opener, url), interval=1)
        self.assertEqual(waiting, ['PowerContext'])


def make_delivery_copy(base, keep_dirs=(), cite_dirs=(), cite_revision=None):
    """复制一份交付目录到临时目录，供验收脚本的负例与组合测试使用。

    keep_dirs 之外的运行归档会被删掉，避免其它归档干扰判定；
    cite_dirs 里的运行编号会被写进 ACCEPTANCE.md，使「文档引用归档的真实运行记录」
    这一项仍然成立。所有操作只发生在临时目录里，不碰原始 evidence。
    """
    work = base / 'minimax'
    shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns('__pycache__', '.runtime'))
    runs = work / 'evidence' / 'run'
    root_run = json.loads((runs / 'summary.json').read_text(encoding='utf-8'))['run_id']
    keep = set(keep_dirs) | {root_run}
    for other in list(runs.iterdir()):
        if other.is_dir() and other.name not in keep:
            shutil.rmtree(other)
    if cite_dirs:
        revisions = set()
        for name in cite_dirs:
            summary_path = runs / name / 'summary.json'
            if summary_path.is_file():
                revisions.add(json.loads(summary_path.read_text(encoding='utf-8'))['git_revision'])
        acceptance = work / 'ACCEPTANCE.md'
        text = acceptance.read_text(encoding='utf-8')
        for name in cite_dirs:
            text = re.sub(r'\b[0-9a-f]{12}\b', name, text)
        revision = cite_revision or (revisions.pop() if len(revisions) == 1 else None)
        if revision:
            text = re.sub(r'\b[0-9a-f]{40}\b', revision, text)
        acceptance.write_text(text, encoding='utf-8', newline='\n')
    return work


class RecoveryRoundTests(unittest.TestCase):
    """合法恢复记录：第一轮回复里没有 Python 代码块，第二轮修正成功。

    minimax_agent 允许这种恢复（第一轮 code_sha256=None、测试退出码非 0，
    失败信息保留），验收脚本必须**接受**这种归档，而不是当成「缺摘要」拒绝掉。
    这里只模拟 call_minimax；main、子进程里的 unittest 执行、证据写入都是真的。
    """

    ARCHIVE = '0a0a0a0a0a0a'
    REVISION = 'f' * 40

    def build_recovery_archive(self, base):
        """跑真实 main，把产出组装成一份成功 live 归档。"""
        work = base / 'live'
        work.mkdir()
        ctx = fake_ctx()
        ctx_path = work / 'ctx.json'
        ctx_path.write_text(json.dumps(ctx, ensure_ascii=False), encoding='utf-8')
        evidence = work / 'ev'
        output = work / 'out' / 'task_service.py'
        output.parent.mkdir()
        calls = []

        def fake_call(messages, model, base_url, key):
            calls.append(messages)
            if len(calls) == 1:
                content = '我先确认一下需要改哪个函数，稍等。'      # 没有代码块
            else:
                content = '```python\n' + NEW_CODE + '```'
            return ({'model': model, 'messages': messages},
                    {'id': f'resp-{len(calls)}', 'model': 'MiniMax-M3',
                     'usage': {'total_tokens': 100},
                     'choices': [{'message': {'content': content}}]}, 0.01)

        original_call, original_argv = minimax_agent.call_minimax, sys.argv
        original_key = os.environ.get('MINIMAX_API_KEY')
        minimax_agent.call_minimax = fake_call
        sys.argv = ['minimax_agent.py', '--context-file', str(ctx_path), '--output', str(output),
                    '--evidence-dir', str(evidence)]
        os.environ['MINIMAX_API_KEY'] = 'dummy'
        try:
            minimax_agent.main()
        finally:
            minimax_agent.call_minimax, sys.argv = original_call, original_argv
            if original_key is None:
                os.environ.pop('MINIMAX_API_KEY', None)
            else:
                os.environ['MINIMAX_API_KEY'] = original_key

        self.assertEqual(len(calls), 2, '应实际调用两轮')
        record = json.loads(sorted(evidence.glob('*-exchange.json'))[0].read_text(encoding='utf-8'))
        self.assertIsNone(record['rounds'][0]['code_sha256'], '第一轮应没有代码摘要')
        self.assertEqual(record['rounds'][0]['tests']['exit_code'], 1, '第一轮应是失败')
        self.assertEqual(record['rounds'][1]['tests']['exit_code'], 0, '第二轮应通过')
        self.assertTrue(record['rounds'][0]['tests']['output'], '第一轮的失败信息必须保留')

        archive = base / 'archive'
        archive.mkdir()
        (archive / '20260101T000000Z-exchange.json').write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        shutil.copyfile(output, archive / 'task_service.py')
        # steps.json：context-before-change 必须与 main 用的那份上下文一致
        steps = [
            {'step': 'context-before-change', 'command': ['(internal)'], 'exit_code': 0,
             'stdout': json.dumps(ctx, ensure_ascii=False), 'stderr': ''},
            {'step': 'tests-after-target', 'command': ['(internal)'], 'exit_code': 0,
             'stdout': '', 'stderr': 'OK'},
            {'step': 'tests-after-regression', 'command': ['(internal)'], 'exit_code': 0,
             'stdout': '', 'stderr': 'OK'},
        ]
        (archive / 'steps.json').write_text(json.dumps(steps, ensure_ascii=False, indent=2), encoding='utf-8')
        tests_raw = hashlib.sha256((ROOT / 'sample' / 'test_task_service.py').read_bytes()).hexdigest()
        tests_lf = hashlib.sha256(
            (ROOT / 'sample' / 'test_task_service.py').read_bytes().replace(b'\r\n', b'\n')).hexdigest()
        summary = {'run_id': self.ARCHIVE, 'git_revision': self.REVISION, 'project': 'p',
                   'task': 'TASK-2', 'minimax': 'live', 'scope_id': 'scp_test',
                   'before_sha256': record['before_sha256'], 'after_sha256': record['after_sha256'],
                   'tests_sha256': tests_raw, 'tests_sha256_lf': tests_lf, 'result': 'PASS'}
        (archive / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                               encoding='utf-8')
        return archive

    def test_recovery_archive_passes_acceptance(self):
        """合法的「无代码回复 → 修正成功」归档必须通过真实验收入口。"""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            archive = self.build_recovery_archive(base)
            work = make_delivery_copy(base / 'copy', keep_dirs=[self.ARCHIVE],
                                      cite_dirs=[self.ARCHIVE], cite_revision=self.REVISION)
            shutil.copytree(archive, work / 'evidence' / 'run' / self.ARCHIVE)
            result = subprocess.run([sys.executable, str(work / 'verify_acceptance.py')],
                                    cwd=work, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0,
                             f'合法的恢复归档被拒绝：\n{result.stdout[-3000:]}\n{result.stderr[-800:]}')


class AcceptanceNegativeTests(unittest.TestCase):
    """验收脚本自身的负例：损坏的成功归档必须让 verify_acceptance.py 失败。

    构造两份受控归档（目录名用纯十六进制，便于验收文档按运行编号引用）：
      OLDER = 'ff00ff00ff00'  旧的成功归档（目录名字典序**大**）
      NEWER = '0aaa00bbcc00'  较新的成功归档（目录名字典序**更小**）

    「较新」由 exchange 里的 time_utc 决定，与目录名无关——改目录名不应改变
    「最新一次」的挑选结果。每次只破坏一个因素，然后调用真实的验收入口。
    """

    OLDER = 'ff00ff00ff00'
    NEWER = '0aaa00bbcc00'
    TEMPLATE = '5b3abb06746b'

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.work = self.build_copy(Path(self.temporary.name))

    def build_copy(self, base):
        """复制一份交付目录，摆好两份受控归档，并把验收文档改为引用它们。"""
        work = base / 'minimax'
        shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns('__pycache__', '.runtime'))
        runs = work / 'evidence' / 'run'
        template = runs / self.TEMPLATE
        self.assertTrue(template.is_dir(), '缺少可用的实时归档模板')
        self.revision = json.loads((template / 'summary.json').read_text(encoding='utf-8'))['git_revision']

        for name, stamp in ((self.OLDER, '20200101T000000Z'), (self.NEWER, '20990101T000000Z')):
            target = runs / name
            shutil.copytree(template, target)
            path = sorted(target.glob('*-exchange.json'))[0]
            record = json.loads(path.read_text(encoding='utf-8'))
            record['time_utc'] = stamp
            path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
            summary_path = target / 'summary.json'
            summary = json.loads(summary_path.read_text(encoding='utf-8'))
            summary['run_id'] = name
            summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')

        # 只保留根目录所指的归档与这两份受控归档，其余删掉，避免干扰判定
        root_run = json.loads((runs / 'summary.json').read_text(encoding='utf-8'))['run_id']
        for other in list(runs.iterdir()):
            if other.is_dir() and other.name not in (self.OLDER, self.NEWER, root_run):
                shutil.rmtree(other)
        # 验收文档改为引用受控归档，避免「文档引用未归档」这一项干扰负例
        acceptance = work / 'ACCEPTANCE.md'
        text = acceptance.read_text(encoding='utf-8')
        text = re.sub(r'\b[0-9a-f]{12}\b', self.NEWER, text)
        text = re.sub(r'\b[0-9a-f]{40}\b', self.revision, text)
        acceptance.write_text(text, encoding='utf-8', newline='\n')
        return work

    # ---- 验收入口 -------------------------------------------------
    def run_check(self, work=None):
        work = work or self.work
        return subprocess.run([sys.executable, str(work / 'verify_acceptance.py')],
                              cwd=work, capture_output=True, text=True)

    def test_untouched_archives_pass(self):
        """正例：两份受控归档都没被破坏时，验收入口必须通过。"""
        result = self.run_check()
        self.assertEqual(result.returncode, 0, f'未被破坏的归档却没通过：\n{result.stdout[-2000:]}')

    def test_crlf_archive_source_still_passes(self):
        """正例：归档源码是 CRLF（Windows 检出）时仍应通过——跨平台兼容没有回退。

        归档源码在 Windows 上检出会被转成 CRLF，比对必须按 LF 归一化口径。
        """
        produced = self.work / 'evidence' / 'run' / self.NEWER / 'task_service.py'
        text = produced.read_text(encoding='utf-8')
        produced.write_bytes(text.replace('\n', '\r\n').encode('utf-8'))
        self.assertNotEqual(produced.read_bytes(), text.encode('utf-8'))
        result = self.run_check()
        self.assertEqual(result.returncode, 0,
                         f'CRLF 归档源码应按 LF 归一化口径通过，却没通过：\n{result.stdout[-2000:]}')

    def test_negative_cases(self):
        for name, mutate in NEGATIVE_CASES:
            with self.subTest(case=name):
                # 每个负例从干净的副本开始
                with tempfile.TemporaryDirectory() as tmp:
                    work = self.build_copy(Path(tmp))
                    mutate(work / 'evidence' / 'run' / self.NEWER)
                    result = self.run_check(work)
                    self.assertNotEqual(result.returncode, 0,
                                        f'负例「{name}」未被检出：损坏的成功归档仍被判为通过')
                    self.assertIn(self.NEWER, result.stdout,
                                  f'负例「{name}」未指出具体是哪个运行：\n{result.stdout[-1500:]}')


# ---------------------------------------------------------------- 负例定义
def _exchange_path(run_dir):
    return sorted(run_dir.glob('*-exchange.json'))[0]


def _load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def break_first_prompt(run_dir):
    """破坏首轮的任务 prompt。"""
    path = _exchange_path(run_dir)
    record = _load(path)
    for message in record['rounds'][0]['request']['messages']:
        if message.get('role') == 'user':
            message['content'] = message['content'] + '\n\n（这段提示与该次上下文不一致）'
    _save(path, record)


def break_reply_code(run_dir):
    """破坏回复中的代码。

    同时把该轮的 code_sha256 重算成新代码的哈希，让「code_sha256 与回复一致」
    这一项保持自洽——被破坏的只有「回复里的代码与归档产出对不上」这一项。
    """
    path = _exchange_path(run_dir)
    record = _load(path)
    last = record['rounds'][-1]
    content = last['response']['choices'][0]['message']['content']
    start = content.index('```') + 3
    end = content.rindex('```')
    body = content[start:end]
    changed = body.replace('== wanted', '!= wanted')
    if changed == body:                      # 夹具里没有这句时，退一步改常量
        changed = body.replace("'todo'", "'TODO'")
    last['response']['choices'][0]['message']['content'] = content[:start] + changed + content[end:]
    last['code_sha256'] = hashlib.sha256(
        minimax_agent.extract_code(last['response']['choices'][0]['message']['content']).encode()).hexdigest()
    _save(path, record)


def break_code_sha(run_dir):
    """破坏某一轮的 code_sha256。"""
    path = _exchange_path(run_dir)
    record = _load(path)
    record['rounds'][0]['code_sha256'] = '0' * 64
    _save(path, record)


def break_exchange_after(run_dir):
    """破坏 exchange 里的产出摘要。"""
    path = _exchange_path(run_dir)
    record = _load(path)
    record['after_sha256'] = 'f' * 64
    _save(path, record)


def break_summary_after(run_dir):
    """破坏 summary 里的产出摘要。"""
    path = run_dir / 'summary.json'
    summary = _load(path)
    summary['after_sha256'] = 'e' * 64
    _save(path, summary)


def break_archived_source(run_dir):
    """破坏归档源码：只追加一行不影响行为的注释。"""
    path = run_dir / 'task_service.py'
    path.write_text(path.read_text(encoding='utf-8') + '\n# 归档源码被改动过\n', encoding='utf-8')


def break_test_summary(run_dir):
    """破坏测试摘要。"""
    path = run_dir / 'summary.json'
    summary = _load(path)
    summary['tests_sha256_lf'] = 'd' * 64
    summary['tests_sha256'] = 'd' * 64
    _save(path, summary)


def remove_exchange(run_dir):
    """缺少 exchange 记录。"""
    for path in run_dir.glob('*-exchange.json'):
        path.unlink()


def empty_rounds(run_dir):
    """exchange 的 rounds 为空。"""
    path = _exchange_path(run_dir)
    record = _load(path)
    record['rounds'] = []
    _save(path, record)


def remove_response_id(run_dir):
    """缺响应 ID。"""
    path = _exchange_path(run_dir)
    record = _load(path)
    record['rounds'][0]['response'].pop('id', None)
    _save(path, record)


def remove_usage(run_dir):
    """缺 usage。"""
    path = _exchange_path(run_dir)
    record = _load(path)
    record['rounds'][-1]['response'].pop('usage', None)
    _save(path, record)


def remove_produced(run_dir):
    """缺产出文件。"""
    (run_dir / 'task_service.py').unlink()


def fail_last_round_tests(run_dir):
    """声明成功但末轮测试失败。"""
    path = _exchange_path(run_dir)
    record = _load(path)
    record['rounds'][-1]['tests']['exit_code'] = 1
    _save(path, record)


def drop_code_sha_field(run_dir):
    """有代码，却缺 code_sha256 字段——不能冒充合法的「显式 None」。"""
    path = _exchange_path(run_dir)
    record = _load(path)
    record['rounds'][0].pop('code_sha256', None)
    _save(path, record)


def code_sha_none_with_code(run_dir):
    """有代码，但 code_sha256 被写成 None。"""
    path = _exchange_path(run_dir)
    record = _load(path)
    record['rounds'][0]['code_sha256'] = None
    _save(path, record)


def last_round_without_code(run_dir):
    """末轮没有产出代码，却声明成功。"""
    path = _exchange_path(run_dir)
    record = _load(path)
    last = record['rounds'][-1]
    last['response']['choices'][0]['message']['content'] = '我这边没能给出完整代码。'
    last['code_sha256'] = None
    last['tests']['exit_code'] = 1
    _save(path, record)


def last_round_code_sha_none(run_dir):
    """末轮回复里有代码，摘要却是 None。"""
    path = _exchange_path(run_dir)
    record = _load(path)
    record['rounds'][-1]['code_sha256'] = None
    _save(path, record)


def drop_exchange_after(run_dir):
    """删掉 exchange.after_sha256。"""
    path = _exchange_path(run_dir)
    record = _load(path)
    record.pop('after_sha256', None)
    _save(path, record)


def exchange_after_none(run_dir):
    """exchange.after_sha256 为 None。"""
    path = _exchange_path(run_dir)
    record = _load(path)
    record['after_sha256'] = None
    _save(path, record)


def exchange_after_empty(run_dir):
    """exchange.after_sha256 为空字符串。"""
    path = _exchange_path(run_dir)
    record = _load(path)
    record['after_sha256'] = ''
    _save(path, record)


def drop_summary_after(run_dir):
    """删掉 summary.after_sha256。"""
    path = run_dir / 'summary.json'
    summary = _load(path)
    summary.pop('after_sha256', None)
    _save(path, summary)


def summary_after_none(run_dir):
    """summary.after_sha256 为 None。"""
    path = run_dir / 'summary.json'
    summary = _load(path)
    summary['after_sha256'] = None
    _save(path, summary)


def summary_after_empty(run_dir):
    """summary.after_sha256 为空字符串。"""
    path = run_dir / 'summary.json'
    summary = _load(path)
    summary['after_sha256'] = ''
    _save(path, summary)


NEGATIVE_CASES = [
    ('首轮任务 prompt 与上下文不一致', break_first_prompt),
    ('回复中的代码与归档产出对不上', break_reply_code),
    ('某一轮的 code_sha256 与回复不符', break_code_sha),
    ('exchange 的产出摘要被改', break_exchange_after),
    ('summary 的产出摘要被改', break_summary_after),
    ('归档源码被改（追加注释）', break_archived_source),
    ('测试摘要被改', break_test_summary),
    ('缺 exchange 记录', remove_exchange),
    ('exchange 的 rounds 为空', empty_rounds),
    ('缺响应 ID', remove_response_id),
    ('缺 usage', remove_usage),
    ('缺产出文件', remove_produced),
    ('声明成功但末轮测试失败', fail_last_round_tests),
    # ---- 合法恢复记录与必需摘要 ----
    ('有代码却缺 code_sha256 字段', drop_code_sha_field),
    ('有代码但 code_sha256 为 None', code_sha_none_with_code),
    ('末轮没有产出代码却声明成功', last_round_without_code),
    ('末轮 code_sha256 为 None', last_round_code_sha_none),
    ('删掉 exchange.after_sha256', drop_exchange_after),
    ('exchange.after_sha256 为 None', exchange_after_none),
    ('exchange.after_sha256 为空字符串', exchange_after_empty),
    ('删掉 summary.after_sha256', drop_summary_after),
    ('summary.after_sha256 为 None', summary_after_none),
    ('summary.after_sha256 为空字符串', summary_after_empty),
]


if __name__ == '__main__':
    unittest.main(verbosity=2)
