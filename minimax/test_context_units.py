"""上下文模块的离线单元测试（不连接 seekdb / PowerContext / MiniMax）。

  python -B -m unittest -v test_context_units
覆盖：规格替代与废弃、验证结果按版本判定是否仍适用、进展只采纳 task-progress 记录、提示中包含验证结果。
"""
import json
import unittest

import context
import minimax_agent


def row(entry_id, body, path='spec.md'):
    return {'path': path, 'entry_id': entry_id, 'body': body}


def memory(kind, value, state='active'):
    return {'kind': kind, 'state': state, 'text': json.dumps(value, ensure_ascii=False)}


BASIS = {'spec_sha256': 's1', 'code_sha256': {'work/a.py': 'c1'}, 'tests_sha256': {'t.py': 't1'}}


class SpecStatusTests(unittest.TestCase):
    def test_supersede(self):
        status = context.spec_status([row('TASK-1', '旧规则'), row('TASK-3', '> 替代：TASK-1\n新规则')])
        self.assertEqual(status['TASK-1']['status'], 'superseded')
        self.assertEqual(status['TASK-1']['by'], 'TASK-3')
        self.assertEqual(status['TASK-3']['status'], 'active')

    def test_english_marker_and_multiple_ids(self):
        status = context.spec_status([row('A-1', 'x'), row('A-2', 'y'), row('A-3', '> Supersedes: A-1, A-2')])
        self.assertEqual([status[k]['status'] for k in ('A-1', 'A-2', 'A-3')], ['superseded', 'superseded', 'active'])

    def test_revoked(self):
        status = context.spec_status([row('TASK-1', '> 状态：废弃\n旧规则'), row('TASK-2', '规则')])
        self.assertEqual(status['TASK-1']['status'], 'revoked')
        self.assertEqual(status['TASK-2']['status'], 'active')

    def test_revoked_entry_cannot_supersede(self):
        status = context.spec_status([row('TASK-1', '规则'), row('TASK-3', '> 状态：废弃\n> 替代：TASK-1')])
        self.assertEqual(status['TASK-1']['status'], 'active')

    def test_plain_quote_is_not_a_marker(self):
        status = context.spec_status([row('TASK-1', '规则'), row('TASK-2', '说明里提到 替代：TASK-1 只是文字')])
        self.assertEqual(status['TASK-1']['status'], 'active')

    def test_basis_tracks_spec_text(self):
        sources = [{'path': 'work/a.py', 'kind': 'code', 'sha256': 'c1'}, {'path': 't.py', 'kind': 'test', 'sha256': 't1'}]
        first = context.basis_of([row('TASK-2', '规则')], sources)
        second = context.basis_of([row('TASK-2', '规则\n补充')], sources)
        self.assertNotEqual(first['spec_sha256'], second['spec_sha256'])
        self.assertEqual(first['code_sha256'], second['code_sha256'])


class VerificationTests(unittest.TestCase):
    def test_current_and_stale(self):
        record = {'stage': 'after', 'basis': BASIS}
        self.assertEqual(context.assess(record, BASIS)['validity'], 'current')
        for key, label in (('spec_sha256', 'spec'), ('code_sha256', 'code'), ('tests_sha256', 'tests')):
            changed = dict(BASIS, **{key: 'other'})
            result = context.assess(record, changed)
            self.assertEqual((result['validity'], result['changed']), ('stale', [label]))

    def test_unknown_without_basis(self):
        self.assertEqual(context.assess({'stage': 'after'}, BASIS)['validity'], 'unknown')

    def test_progress_marks_latest_and_adds_todo(self):
        state = {'entries': [memory('task-progress', {'task': 'TASK-2', 'completed': ['done'], 'todo': [],
                                                       'tests': [{'stage': 'after', 'basis': BASIS}], 'saved_at': 1})]}
        current = context.latest_progress(state, 'TASK-2', BASIS)
        self.assertEqual((current['verification_status'], current['needs_reverification'], current['todo']),
                         ('current', False, []))
        stale = context.latest_progress(state, 'TASK-2', dict(BASIS, spec_sha256='new'))
        self.assertEqual(stale['verification_status'], 'stale')
        self.assertTrue(stale['needs_reverification'])
        self.assertIn('规格', stale['todo'][-1])
        # 历史结果原样保留
        self.assertEqual(stale['verification'][0]['stage'], 'after')


class ProgressFilterTests(unittest.TestCase):
    def test_only_task_progress_is_used(self):
        state = {'entries': [
            memory('task-progress', {'task': 'TASK-2', 'completed': ['real'], 'todo': [], 'tests': [], 'saved_at': 1}),
            memory('note', {'task': 'TASK-2', 'completed': ['forged'], 'todo': [], 'tests': [], 'saved_at': 9}),
            memory('task-progress', {'task': 'TASK-2', 'completed': ['archived'], 'todo': [], 'tests': [],
                                     'saved_at': 8}, state='archived'),
            memory('task-progress', {'task': 'TASK-2', 'completed': 'not-a-list', 'saved_at': 7}),
            memory('task-progress', {'task': 'TASK-9', 'completed': ['other task'], 'todo': [], 'tests': [], 'saved_at': 6}),
        ]}
        self.assertEqual(context.latest_progress(state, 'TASK-2')['completed'], ['real'])

    def test_newest_by_saved_at(self):
        state = {'entries': [
            memory('task-progress', {'task': 'TASK-2', 'completed': ['new'], 'todo': [], 'tests': [], 'saved_at': 5}),
            memory('task-progress', {'task': 'TASK-2', 'completed': ['old'], 'todo': [], 'tests': [], 'saved_at': 2}),
        ]}
        self.assertEqual(context.latest_progress(state, 'TASK-2')['completed'], ['new'])

    def test_empty_state(self):
        progress = context.latest_progress({'entries': []}, 'TASK-2')
        self.assertEqual((progress['completed'], progress['verification'], progress['source']), ([], [], None))


class PromptTests(unittest.TestCase):
    def test_prompt_contains_verification_and_inactive_spec(self):
        ctx = {'task': 'TASK-2', 'project': 'p',
               'spec_entries': [{'role': 'implement', 'source': 'spec.md#TASK-2', 'lines': [1, 2], 'title': 't', 'text': '规则'}],
               'inactive_spec_entries': [{'source': 'spec.md#TASK-1', 'title': '旧', 'status': 'superseded',
                                          'reason': '被 TASK-3 替代'}],
               'code_targets': [{'source': 'a.py#f', 'path': 'a.py', 'type': 'FunctionDef', 'lines': [1, 2]}],
               'tests': {'functional': ['t.py#F.test_a'], 'regression': ['t.py#R.test_b']},
               'sources': [{'path': 'a.py', 'content': 'def f(): pass'}, {'path': 't.py', 'content': 'import a'}],
               'progress': {'completed': ['导入'], 'todo': ['修改'],
                            'verification': [{'stage': 'before', 'target_exit': 1, 'regression_exit': 0,
                                              'validity': 'stale', 'changed': ['code']}]}}
        prompt = minimax_agent.build_prompt(ctx)
        self.assertIn('before：功能测试退出码 1，回归测试退出码 0，已过期（变化：code）', prompt)
        self.assertIn('spec.md#TASK-1 旧：被 TASK-3 替代', prompt)


if __name__ == '__main__':
    unittest.main()
