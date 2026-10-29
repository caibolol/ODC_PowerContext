"""工具自身的自检：输出文件校验与就绪探测。

用法（在 minimax/ 目录下）：
    python test_tooling.py

只用到标准库与被测模块，不连接数据库、不需要 PowerContext 在跑。
"""
import http.server
import os
import socketserver
import tempfile
import threading
import unittest
from pathlib import Path
import urllib.request

import minimax_agent
import run_demo

OLD_CODE = 'def list_tasks(tasks, status=None):\n    return list(tasks)\n'
NEW_CODE = ('def list_tasks(tasks, status=None):\n'
            '    if status is None:\n'
            '        return list(tasks)\n'
            '    wanted = status.strip().casefold()\n'
            '    if wanted not in (\'todo\', \'done\'):\n'
            '        raise ValueError("status must be either \'todo\' or \'done\'")\n'
            '    return [t for t in tasks if t.get(\'status\', \'todo\').casefold() == wanted]\n')
TEST_SOURCE = '''import unittest
from task_service import list_tasks


class FeatureTests(unittest.TestCase):
    def test_filter(self):
        rows = [{'id': 1, 'status': 'DONE'}, {'id': 2}]
        self.assertEqual(list_tasks(rows, 'done'), [{'id': 1, 'status': 'DONE'}])


class RegressionTests(unittest.TestCase):
    def test_no_filter(self):
        self.assertEqual(list_tasks([{'id': 1}]), [{'id': 1}])
'''


def fake_ctx():
    return {
        'code_targets': [{'path': 'before/task_service.py', 'symbol': 'list_tasks',
                          'type': 'FunctionDef', 'lines': [1, 2]}],
        'sources': [{'path': 'before/task_service.py', 'kind': 'code', 'content': OLD_CODE},
                    {'path': 'test_task_service.py', 'kind': 'test', 'content': TEST_SOURCE}],
        'tests': {'functional': ['test_task_service.py#FeatureTests.test_filter'],
                  'regression': ['test_task_service.py#RegressionTests.test_no_filter']},
    }


class OutputGuardTests(unittest.TestCase):
    """minimax_agent 的自检必须测到本次输出，而不是目录里残留的旧模块。"""

    def test_rejects_missing_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(SystemExit):
                minimax_agent.check_output(fake_ctx(), Path(temporary) / 'task_service.py')

    def test_rejects_mismatched_filename(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'result.py'
            output.write_text(NEW_CODE, encoding='utf-8')
            with self.assertRaises(SystemExit):
                minimax_agent.check_output(fake_ctx(), output)

    def test_rejects_stale_module_in_same_directory(self):
        """目录里留着上一次的同名模块、而本次输出文件不存在时必须拒绝。

        旧行为下这种情况会 import 到旧代码并给出 OK，是最危险的假通过。
        """
        with tempfile.TemporaryDirectory() as temporary:
            (Path(temporary) / 'task_service.py').write_text(NEW_CODE, encoding='utf-8')
            missing = Path(temporary) / 'sub' / 'task_service.py'
            missing.parent.mkdir()
            with self.assertRaises(SystemExit):
                minimax_agent.check_output(fake_ctx(), missing)

    def test_accepts_existing_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'task_service.py'
            output.write_text(NEW_CODE, encoding='utf-8')
            self.assertEqual(minimax_agent.check_output(fake_ctx(), output), 'task_service')

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


if __name__ == '__main__':
    unittest.main(verbosity=2)
