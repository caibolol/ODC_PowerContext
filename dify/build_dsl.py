"""生成可导入 Dify 的工作流，游戏逻辑完整保留在 Code 节点。"""
from pathlib import Path
import yaml

root=Path(__file__).parent
nodes=[]
def node(id,title,type,**data):
    nodes.append({'id':id,'type':'custom','position':{'x':len(nodes)*310,'y':200},'width':244,'height':100,'sourcePosition':'right','targetPosition':'left','data':{'title':title,'type':type,'desc':'','selected':False,**data}})
def code(id,title,source,variables,outputs):
    node(id,title,'code',code_language='python3',code=source,variables=[{'variable':k,'value_selector':v} for k,v in variables.items()],outputs={k:{'type':v,'children':None} for k,v in outputs.items()})
node('start','侦探身份与行动','start',variables=[{'label':'玩家代号（英文字母、数字、下划线）','variable':'player_id','type':'text-input','required':True,'max_length':64,'options':[]},{'label':'行动：开始 / 提示 / 答案 / 继续 / 重开','variable':'action','type':'text-input','required':True,'max_length':200,'options':[]}])
code('prepare','校验代号',"import re\ndef main(player_id: str) -> dict:\n    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', player_id):\n        raise ValueError('玩家代号格式不正确')\n    return {'player':player_id}\n",{'player_id':['start','player_id']},{'player':'string'})
url='http://host.docker.internal:18747/state/{{#prepare.player#}}'
def http(id,title,method,body):
    node(id,title,'http-request',method=method,url=url,authorization={'type':'no-auth'},headers='Content-Type:application/json',params='',body=body,timeout={'connect':10,'read':30,'write':30},retry_config={'retry_enabled':False,'max_retries':0,'retry_interval':1000},ssl_verify=True)
http('load','从 seekdb 恢复档案','GET',{'type':'none','data':[]})
code('game','推理、线索与关卡规则',root.joinpath('game.py').read_text(encoding='utf-8'),{'body':['load','body'],'action':['start','action']},{'payload':'string','message':'string'})
http('save','将本回合写入 seekdb','POST',{'type':'json','data':[{'key':'','type':'text','value':'{{#game.payload#}}'}]})
code('verify','确认存档再回复',"import json\ndef main(body: str, message: str) -> dict:\n    result=json.loads(body)\n    if not result.get('saved'):\n        raise ValueError(result.get('error','存档失败，请重试'))\n    return {'answer':message+'\\n档案已保存，版本 '+str(result['revision'])+'。'}\n",{'body':['save','body'],'message':['game','message']},{'answer':'string'})
node('end','侦探回合结果','end',outputs=[{'value_selector':['verify','answer'],'value_type':'string','variable':'answer'}])
edges=[{'id':a['id']+'-'+b['id'],'source':a['id'],'target':b['id'],'sourceHandle':'source','targetHandle':'target','type':'custom','data':{'sourceType':a['data']['type'],'targetType':b['data']['type'],'isInIteration':False,'isInLoop':False}} for a,b in zip(nodes,nodes[1:])]
dsl={'version':'0.3.1','kind':'app','app':{'name':'记忆侦探：三扇数据库之门','description':'Dify 主导规则与回合编排，seekdb 保存跨会话进度。无需外部模型密钥。','icon':'🗝️','icon_background':'#E4FBCC','mode':'workflow','use_icon_as_answer_icon':False},'dependencies':[],'workflow':{'conversation_variables':[],'environment_variables':[],'features':{'file_upload':{'enabled':False},'opening_statement':'','retriever_resource':{'enabled':False},'sensitive_word_avoidance':{'enabled':False},'speech_to_text':{'enabled':False},'suggested_questions':[],'suggested_questions_after_answer':{'enabled':False},'text_to_speech':{'enabled':False}},'graph':{'nodes':nodes,'edges':edges,'viewport':{'x':0,'y':0,'zoom':0.7}}}}
root.joinpath('detective.yml').write_text(yaml.safe_dump(dsl,allow_unicode=True,sort_keys=False),encoding='utf-8')
