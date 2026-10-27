"""Dify Code 节点中的完整游戏规则；不在存储服务中执行。"""
import json

ROOMS = [
    {"name": "丢失的检索室", "clue": "管理员只记得一个词，访客只记得意思。两份排名需要合成同一份答案。请说出这种检索方式。", "answers": ["混合检索", "hybrid search", "混合搜索"], "hint": "同时使用关键词和向量，答案是四个汉字。", "fact": "混合检索结合关键词与向量相似度，可由数据库使用 RRF 融合候选排名。"},
    {"name": "时间回声走廊", "clue": "你关掉应用后再回来，我仍记得你的分数。只存在浏览器变量里的我做不到。请说出这种能力。", "answers": ["持久化", "persistence", "数据持久化"], "hint": "把状态保存进数据库，而不是只留在内存。", "fact": "本游戏每回合从 seekdb 读取进度并持久化，Dify 不依赖上一次运行的临时变量。"},
    {"name": "并发双影门", "clue": "两名分身同时读取旧进度，各自提交。怎样避免后提交的人覆盖先提交者？请说出锁策略。", "answers": ["乐观锁", "optimistic locking", "版本号", "版本检查"], "hint": "读取时带回 revision，写入时比较这个版本号。", "fact": "本游戏用带 revision 条件的 UPDATE 实现乐观并发控制，冲突时返回 409。"},
]

def main(body: str, action: str) -> dict:
    loaded=json.loads(body)
    state=loaded['state']
    action=action.strip()
    command=action.casefold()
    if command in ['重开','restart']:
        state={'room':0,'score':0,'attempts':0,'hints':0,'history':[]}
        message='新的档案已开启。'
    elif state['room'] >= len(ROOMS):
        message='档案已经解密！输入“重开”可重新挑战。'
    elif command in ['提示','hint']:
        state['hints']+=1
        message=ROOMS[state['room']]['hint']
    elif command in ['开始','继续','start','continue','']:
        message='欢迎回来，侦探。进度已从 seekdb 恢复。'
    else:
        room=ROOMS[state['room']]
        state['attempts']+=1
        correct=command in room['answers']
        state['history'].append({'room':state['room'],'answer':action[:200],'correct':correct})
        state['history']=state['history'][-100:]
        if correct:
            state['score']+=max(1,10-state['hints']*2)
            state['room']+=1
            state['hints']=0
            message='破解成功！'+room['fact']
        else:
            message='还没有匹配证据。再想一想，或输入“提示”。'
    if state['room']<len(ROOMS):
        room=ROOMS[state['room']]
        message+='\n\n【'+room['name']+'】\n'+room['clue']
    else:
        message+='\n\n全部三扇门已打开。'
    message+='\n\n分数：'+str(state['score'])+' / 30；作答次数：'+str(state['attempts'])+'。'
    return {'payload':json.dumps({'state':state,'revision':loaded['revision']},ensure_ascii=False),'message':message}
