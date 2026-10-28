"""SDD 上下文入口：seekdb 保存来源，PowerContext 保存跨进程任务状态。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.request

import pymysql

ROOT = Path(__file__).resolve().parent


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
    return connection


def ingest(project, manifest):
    manifest = Path(manifest).resolve()
    data = json.loads(manifest.read_text(encoding='utf-8'))
    rows = []
    for item in data['sources']:
        path = (manifest.parent / item['path']).resolve()
        if not path.is_relative_to(manifest.parent):
            raise ValueError('来源必须位于项目目录内')
        content = path.read_text(encoding='utf-8')
        rows.append((project, item['path'], item['kind'], json.dumps(item['tasks']),
                     content, hashlib.sha256(content.encode()).hexdigest()))
    # 先读完并校验全部来源，再事务替换旧索引，移除过期内容。
    connection = database()
    try:
        with connection.cursor() as cursor:
            cursor.execute('DELETE FROM sdd_sources WHERE project_id=%s', (project,))
            cursor.executemany('INSERT INTO sdd_sources VALUES (%s,%s,%s,%s,%s,%s)', rows)
        connection.commit()
    finally:
        connection.close()
    return {'project': project, 'imported': len(rows)}


def scope(key):
    return pc('/v1/scopes', {'title': 'MiniMax SDD 验证任务',
        'summary': '独立比赛样例的开发进展和验证结果', 'idempotency_key': key})['scope_id']


def context(project, task, scope_id):
    connection = database()
    sql = 'SELECT path,kind,tasks,content,sha256 FROM sdd_sources WHERE project_id=%s ORDER BY kind,path'
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, (project,))
            rows = cursor.fetchall()
    finally:
        connection.close()
    sources = [row for row in rows if task in json.loads(row['tasks'])]
    if not sources:
        raise ValueError('该任务没有导入的来源')
    state = pc('/v1/memory/entries/list', {'scope_id': scope_id})
    return {'project': project, 'task': task, 'sources': sources,
            'previous_state': state, 'query': {'sql': sql, 'parameters': [project],
            'database_rows': len(rows), 'selected_rows': len(sources)}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
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
