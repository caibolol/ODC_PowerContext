import copy
import unittest
from task_service import list_tasks


class RegressionTests(unittest.TestCase):
    def test_no_filter(self):
        rows = [{'id': 2, 'status': 'done'}, {'id': 1}]
        result = list_tasks(rows)
        self.assertEqual(result, rows)
        self.assertIsNot(result, rows)

    def test_empty_unfiltered(self):
        self.assertEqual(list_tasks([]), [])


class FeatureTests(unittest.TestCase):
    def test_done(self):
        rows = [{'id': 1}, {'id': 2, 'status': 'DONE'}, {'id': 3, 'status': ' DONE '}]
        self.assertEqual(list_tasks(rows, 'done'), [rows[1]])

    def test_normalization_and_default(self):
        rows = [{'id': 3}, {'id': 1, 'status': 'TODO'}, {'id': 2, 'status': 'done'}]
        self.assertEqual(list_tasks(rows, ' ToDo '), rows[:2])

    def test_invalid(self):
        for value in ('', 'pending', '   '):
            with self.subTest(value=value), self.assertRaises(ValueError):
                list_tasks([], value)

    def test_empty_filtered(self):
        self.assertEqual(list_tasks([], 'done'), [])

    def test_no_mutation(self):
        rows = [{'id': 1}, {'id': 2, 'status': 'done'}]
        snapshot = copy.deepcopy(rows)
        list_tasks(rows, 'todo')
        self.assertEqual(rows, snapshot)


if __name__ == '__main__':
    unittest.main()
