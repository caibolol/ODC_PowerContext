"""SDD 上下文入口：seekdb 保存来源与条目索引，PowerContext 保存跨进程任务状态。

命令：
  ingest   导入清单中的规格、代码、测试，并在 seekdb 建立规格条目与代码/测试符号索引
  scope    创建（幂等）PowerContext scope
  context  按任务从 seekdb 查询适用的规格条目、需修改的代码符号、验证测试，并读取任务状态
  save     把任务状态 JSON 写入 PowerContext
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.request

import pymysql

ROOT = Path(__file__).resolve().parent
# 规格条目标题：## TASK-2 状态筛选
SPEC_HEADING = re.compile(r'^##\s+([A-Za-z][\w.-]*-\d+)\s*(.*)$')
# 规格正文中引用的函数：`list_tasks(...)`
SPEC_SYMBOL = re.compile(r'`([A-Za-z_]\w*)\(')


def pc(path, payload):
    base = os.getenv('PC_URL', 'http://127.0.0.1:18752').rstrip('/')
    headers = {'Content-Type': 'application/json'}
    if os.getenv('PC_TOKEN'):
        headers['Authorization'] = 'Bearer ' + os.environ['PC_TOKEN']
    request = urllib.request.Request(base + path, json.dumps(payload).encode(), headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def database():
    name = os.getenv('DB_NAME', 'minimax_sdd')
    if not re.fullmatch(r'[a-zA-Z0-9_]+', name):
        raise ValueError('DB_NAME 只允许字母、数字和下划线')
    connection = pymysql.connect(host=os.getenv('DB_HOST', '127.0.0.1'),
        port=int(os.getenv('DB_PORT', '18753')), user=os.getenv('DB_USER', 'root'),
        password=os.getenv('DB_PASSWORD', ''), charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor, connect_timeout=10)
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE DATABASE IF NOT EXISTS `{name}`')
        cursor.execute(f'USE `{name}`')
        cursor.execute('CREATE TABLE IF NOT EXISTS sdd_sources ('
            'project_id VARCHAR(128), path VARCHAR(256), kind VARCHAR(32), '
            'tasks TEXT, content LONGTEXT, sha256 VARCHAR(64), '
            'PRIMARY KEY(project_id,path))')
        # 条目索引：规格条目、代码符号、测试用例各一行
        cursor.execute('CREATE TABLE IF NOT EXISTS sdd_entries ('
            'project_id VARCHAR(128), path VARCHAR(256), kind VARCHAR(32), '
            'entry_id VARCHAR(256), title VARCHAR(512), body LONGTEXT, '
            'line_start INT, line_end INT, refs TEXT, '
            'PRIMARY KEY(project_id,path,entry_id))')
    return connection


def spec_entries(content):
    """按二级标题切分规格；每个条目带编号、标题、正文和引用的函数。"""
    entries, current = [], None
    for number, line in enumerate(content.splitlines(), 1):
        match = SPEC_HEADING.match(line)
        if match:
            # 同一编号的后续小节（例如规格补充）并入同一条目
            current = next((e for e in entries if e['entry_id'] == match.group(1)), None)
            if current is None:
                current = {'entry_id': match.group(1), 'title': match.group(2).strip(),
                           'lines': [], 'line_start': number, 'line_end': number}
                entries.append(current)
            else:
                current['lines'].append(line)
        elif current is not None:
            current['lines'].append(line)
            current['line_end'] = number
    for entry in entries:
        entry['body'] = '\n'.join(entry.pop('lines')).strip()
        entry['refs'] = sorted(set(SPEC_SYMBOL.findall(entry['body'])))
    return entries


def python_entries(content, kind):
    """代码：顶层函数/类；测试：TestCase 中的 test_ 方法，并记录其调用的函数。"""
    tree = ast.parse(content)
    lines = content.splitlines()
    entries = []

    def calls(node):
        return sorted({n.func.id for n in ast.walk(node)
                       if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)})

    for node in tree.body:
        if kind == 'code' and isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            entries.append({'entry_id': node.name, 'title': type(node).__name__,
                            'line_start': node.lineno, 'line_end': node.end_lineno,
                            'body': '\n'.join(lines[node.lineno - 1:node.end_lineno]),
                            'refs': calls(node)})
        elif kind == 'test' and isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name.startswith('test'):
                    entries.append({'entry_id': f'{node.name}.{item.name}', 'title': node.name,
                                    'line_start': item.lineno, 'line_end': item.end_lineno,
                                    'body': '\n'.join(lines[item.lineno - 1:item.end_lineno]),
                                    'refs': calls(item)})
    return entries


def ingest(project, manifest):
    manifest = Path(manifest).resolve()
    data = json.loads(manifest.read_text(encoding='utf-8'))
    rows, entry_rows = [], []
    for item in data['sources']:
        path = (manifest.parent / item['path']).resolve()
        if not path.is_relative_to(manifest.parent):
            raise ValueError('来源必须位于项目目录内')
        content = path.read_text(encoding='utf-8')
        rows.append((project, item['path'], item['kind'], json.dumps(item['tasks']),
                     content, hashlib.sha256(content.encode()).hexdigest()))
        if item['kind'] == 'spec':
            entries = spec_entries(content)
        elif path.suffix == '.py':
            entries = python_entries(content, item['kind'])
        else:
            entries = []
        for entry in entries:
            entry_rows.append((project, item['path'], item['kind'], entry['entry_id'], entry['title'],
                               entry['body'], entry['line_start'], entry['line_end'],
                               json.dumps(entry['refs'])))
    # 先读完并校验全部来源，再事务替换旧索引，移除过期内容。
    connection = database()
    try:
        with connection.cursor() as cursor:
            cursor.execute('DELETE FROM sdd_sources WHERE project_id=%s', (project,))
            cursor.execute('DELETE FROM sdd_entries WHERE project_id=%s', (project,))
            cursor.executemany('INSERT INTO sdd_sources VALUES (%s,%s,%s,%s,%s,%s)', rows)
            if entry_rows:
                cursor.executemany('INSERT INTO sdd_entries VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)', entry_rows)
        connection.commit()
    finally:
        connection.close()
    return {'project': project, 'imported': len(rows), 'indexed_entries': len(entry_rows)}


def scope(key):
    return pc('/v1/scopes', {'title': 'MiniMax SDD 验证任务',
        'summary': '独立比赛样例的开发进展和验证结果', 'idempotency_key': key})['scope_id']


def latest_progress(state, task):
    """PowerContext 中该任务最新一条 task-progress 记录：已完成、待办、验证结果。"""
    best = None
    for entry in (state or {}).get('entries', []):
        try:
            value = json.loads(entry.get('text', ''))
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict) and value.get('task') == task:
            best = value     # 列表按写入顺序返回，保留最后一条
    if best is None:
        return {'completed': [], 'todo': [], 'verification': [], 'source': None}
    return {'completed': best.get('completed', []), 'todo': best.get('todo', []),
            'verification': best.get('tests', []), 'source': 'PowerContext task-progress'}


def context(project, task, scope_id):
    connection = database()
    queries = []

    def query(sql, params):
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
        queries.append({'sql': sql, 'parameters': list(params), 'rows': len(rows)})
        return rows

    try:
        sql = 'SELECT path,kind,tasks,content,sha256 FROM sdd_sources WHERE project_id=%s ORDER BY kind,path'
        rows = query(sql, (project,))
        sources = [row for row in rows if task in json.loads(row['tasks'])]
        if not sources:
            raise ValueError('该任务没有导入的来源')
        paths = [row['path'] for row in sources]
        marks = ','.join(['%s'] * len(paths))
        # 1. 本任务的规格条目（目标），以及同一规格中必须保持的其他条目
        target = query('SELECT path,entry_id,title,body,line_start,line_end,refs FROM sdd_entries '
                       f'WHERE project_id=%s AND kind=%s AND entry_id=%s AND path IN ({marks})',
                       (project, 'spec', task, *paths))
        if not target:
            raise ValueError(f'规格中没有 {task} 条目')
        spec_paths = sorted({row['path'] for row in target})
        spec_marks = ','.join(['%s'] * len(spec_paths))
        preserve = query('SELECT path,entry_id,title,body,line_start,line_end,refs FROM sdd_entries '
                         f'WHERE project_id=%s AND kind=%s AND entry_id<>%s AND path IN ({spec_marks}) '
                         'ORDER BY path,line_start', (project, 'spec', task, *spec_paths))
        # 2. 规格条目引用的代码符号
        symbols = sorted({name for row in target for name in json.loads(row['refs'])})
        code = []
        if symbols:
            symbol_marks = ','.join(['%s'] * len(symbols))
            code = query('SELECT path,entry_id,title,line_start,line_end FROM sdd_entries '
                         f'WHERE project_id=%s AND kind=%s AND entry_id IN ({symbol_marks}) '
                         f'AND path IN ({marks}) ORDER BY path,line_start',
                         (project, 'code', *symbols, *paths))
        # 3. 调用这些符号的测试，按测试类区分功能与回归
        tests = query('SELECT path,entry_id,title,line_start,line_end,refs FROM sdd_entries '
                      f'WHERE project_id=%s AND kind=%s AND path IN ({marks}) ORDER BY path,line_start',
                      (project, 'test', *paths))
    finally:
        connection.close()
    tests = [row for row in tests if set(json.loads(row['refs'])) & set(symbols)]
    state = pc('/v1/memory/entries/list', {'scope_id': scope_id})

    def entry(row, role=None):
        item = {'source': f"{row['path']}#{row['entry_id']}", 'path': row['path'], 'entry_id': row['entry_id'],
                'lines': [row['line_start'], row['line_end']]}
        if 'title' in row and role is not None:
            item.update({'title': row['title'], 'text': row['body'], 'role': role})
        return item

    return {'project': project, 'task': task,
            'spec_entries': [entry(r, 'implement') for r in target] + [entry(r, 'preserve') for r in preserve],
            'code_targets': [dict(entry(r), symbol=r['entry_id'], type=r['title']) for r in code],
            'tests': {
                'functional': [entry(r)['source'] for r in tests if 'regression' not in r['title'].lower()],
                'regression': [entry(r)['source'] for r in tests if 'regression' in r['title'].lower()],
            },
            'progress': latest_progress(state, task),
            'sources': sources,
            'previous_state': state,
            'query': {'sql': sql, 'parameters': [project], 'database_rows': len(rows),
                      'selected_rows': len(sources), 'all_queries': queries}}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('ingest'); p.add_argument('--project', required=True); p.add_argument('--manifest', required=True)
    p = sub.add_parser('scope'); p.add_argument('--key', required=True)
    p = sub.add_parser('context'); p.add_argument('--project', required=True); p.add_argument('--task', required=True); p.add_argument('--scope', required=True)
    p = sub.add_parser('save'); p.add_argument('--scope', required=True); p.add_argument('--state', required=True)
    args = parser.parse_args()
    if args.action == 'ingest':
        result = ingest(args.project, args.manifest)
    elif args.action == 'scope':
        result = {'scope_id': scope(args.key)}
    elif args.action == 'context':
        result = context(args.project, args.task, args.scope)
    else:
        # 用户显式调用 save 时才保存项目状态，不包含账号或密钥。
        state = json.loads(Path(args.state).read_text(encoding='utf-8'))
        result = pc('/v1/memory/remember', {'scope_id': args.scope,
            'kind': 'task-progress', 'text': json.dumps(state, ensure_ascii=False)})
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
