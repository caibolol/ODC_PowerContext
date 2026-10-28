"""从 WorkBuddy 平台自己的变更记录重建本轮 MiniMax 写出的业务代码，并与交付文件比对。

用法（在 minimax/ 目录下）：
    python verify_platform_record.py

只依赖本目录内的文件，不访问本机 WorkBuddy 安装、不需要数据库或网络。
"""
import glob
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RECORD = ROOT / 'evidence' / 'workbuddy-minimax' / 'platform-record'
DELIVERED = ROOT / 'sample' / 'after' / 'task_service.py'
TARGET = 'wb-work' + '\\' + 'task_service.py'


def rebuild(entry):
    """由平台的 unified-diff hunks 重建修改后的文件内容。"""
    lines = []
    for hunk in entry['hunks']:
        for line in hunk['lines']:
            if line.startswith('+++') or line.startswith('---'):
                continue
            if line.startswith('+') or line.startswith(' '):
                lines.append(line[1:])
    return '\n'.join(lines) + '\n'


def main():
    session = json.loads((RECORD / 'session.json').read_text(encoding='utf-8'))
    records = sorted(glob.glob(str(RECORD / 'changes-*.json')))
    if not records:
        raise SystemExit('缺少平台变更记录')

    print('会话 ID   :', session['id'])
    print('模型      :', session['model'], '（WorkBuddy 平台 sessions 表记录）')
    print('工作目录  :', session['cwd'])
    print('上下文用量:', session['session_usage']['used'], '/', session['session_usage']['size'])

    rebuilt = None
    for path in records:
        change = json.loads(Path(path).read_text(encoding='utf-8'))['change']
        print(f"\n变更记录 {Path(path).name}")
        print('  requestId :', change['requestId'])
        print('  summary   :', change['summary'])
        for item in change['files']:
            print(f"    {item['action']:8} +{item['additions']:<4} -{item['deletions']:<4} {item['filePath']}")
            if item['filePath'].endswith(TARGET):
                rebuilt = rebuild(item)

    if rebuilt is None:
        raise SystemExit('平台记录中没有业务代码文件的改动')

    rebuilt_sha = hashlib.sha256(rebuilt.encode('utf-8')).hexdigest()
    delivered_sha = hashlib.sha256(DELIVERED.read_bytes()).hexdigest()
    print('\n由平台 hunk 重建的代码 SHA-256 :', rebuilt_sha)
    print('交付文件 sample/after/task_service.py SHA-256 :', delivered_sha)
    assert rebuilt_sha == delivered_sha, '平台记录与交付文件不一致'
    print('\nPASS: 平台记录中由本轮 MiniMax 写出的业务代码，与提交的 sample/after/task_service.py 逐字节一致。')


if __name__ == '__main__':
    main()
