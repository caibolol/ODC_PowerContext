"""检查 Dify Code 节点源码的状态流转，不代替 Dify 运行验收。"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from game import main


class GameRulesTest(unittest.TestCase):
    def test_complete_restore_and_restart(self):
        saved = {'state': {'room': 0, 'score': 0, 'attempts': 0, 'hints': 0, 'history': []}, 'revision': 7}
        for action in ['混合检索', '继续', '持久化', '乐观锁']:
            result = main(json.dumps(saved), action)
            saved = json.loads(result['payload'])
        self.assertEqual(saved['state']['room'], 3)
        self.assertEqual(saved['state']['score'], 30)
        self.assertEqual(saved['state']['attempts'], 3)
        self.assertEqual(saved['revision'], 7)  # 版本只由数据库成功写入时递增。
        reset = json.loads(main(json.dumps(saved), '重开')['payload'])
        self.assertEqual(reset['state']['history'], [])
        self.assertEqual(reset['state']['score'], 0)
        self.assertEqual(reset['state']['room'], 0)

    def test_hint_and_wrong_answer(self):
        saved = {'state': {'room': 0, 'score': 0, 'attempts': 0, 'hints': 0, 'history': []}, 'revision': 0}
        for action in ['提示', '错误答案', '混合检索']:
            saved = json.loads(main(json.dumps(saved), action)['payload'])
        self.assertEqual(saved['state']['score'], 8)
        self.assertEqual(saved['state']['room'], 1)
        self.assertEqual(saved['state']['attempts'], 2)
        self.assertEqual([x['correct'] for x in saved['state']['history']], [False, True])


if __name__ == '__main__':
    unittest.main()
