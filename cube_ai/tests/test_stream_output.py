"""Regressions for real ChatGPT streams whose terminal response has output=[]."""
import json
from unittest.mock import Mock

import pytest

from cube_ai.config import BuildSpec
from cube_ai.knowledge import Knowledge
from cube_ai.llm import LLMClient,plan,advise
from cube_ai.catalog import Catalog


def stream(*events):
    r=Mock()
    r.iter_lines.return_value=[line for e in events for line in [('data: '+json.dumps(e)).encode(),b'']]
    return r


def item_event(index,item):return dict(type='response.output_item.done',output_index=index,item=item)
def terminal(output=None):return dict(type='response.completed',response=dict(status='completed',output=output or [],usage={'output_tokens':12}))
def message(text):return dict(id='message1',type='message',role='assistant',status='completed',content=[dict(type='output_text',text=text)])


def test_restore_completed_items_and_reasoning_without_terminal_output():
    reasoning=dict(id='reason1',type='reasoning',summary=[],encrypted_content='synthetic-reasoning')
    msg=message('{"ok":true}')
    result=LLMClient._completed_stream(stream(item_event(0,reasoning),item_event(1,msg),terminal()))
    assert result['output']==[reasoning,msg] and result['usage']['output_tokens']==12


def test_terminal_full_output_is_not_duplicated_and_done_item_wins():
    complete=message('completed');stale=message('partial')
    result=LLMClient._completed_stream(stream(item_event(0,complete),terminal([stale])))
    assert result['output']==[complete]


def test_items_follow_output_order_and_repeated_done_does_not_duplicate():
    a=message('first');b=message('second')
    result=LLMClient._completed_stream(stream(item_event(1,b),item_event(0,a),item_event(1,b),terminal()))
    assert result['output']==[a,b]


@pytest.mark.parametrize('events',[
    [terminal()],
    [item_event(0,message('{}'))],
    [item_event(0,message('{}')),dict(type='response.failed',response={'error':{'code':'failed'}})],
    [dict(type='response.output_text.delta',delta='partial'),terminal()],
    [dict(type='response.output_item.added',output_index=0,item={'type':'function_call','name':'lookup_card'}),terminal()],
])
def test_no_success_without_complete_stream_and_items(events):
    with pytest.raises(ValueError):LLMClient._completed_stream(stream(*events))


class ReplayClient:
    style='responses';model='replayed-chatgpt-stream'
    def __init__(self,events):self.events=iter(events);self.histories=[]
    def request(self,messages,**kwargs):
        self.histories.append(list(messages))
        return LLMClient._completed_stream(stream(*next(self.events)))


def plan_data():
    spec=BuildSpec.from_dict({'bracket':3}).to_dict()
    return dict(spec,explanation='600 张 Commander，Bracket 3，保留现有约束。',unapplied_requests=[])


def test_plan_screenshot_request_succeeds_with_empty_terminal_output():
    client=ReplayClient([[item_event(0,message(json.dumps(plan_data()))),terminal()]])
    p=plan('做commander cube 600张，多一些交互，强度bracket3',BuildSpec.from_dict({'bracket':3}),Knowledge(),client)
    assert p['spec']['size']==600 and p['spec']['bracket']==3 and p['spec']['mode']=='commander'


@pytest.mark.parametrize('reply,match',[
    ({'status':'completed','output':[]},'没有返回规划正文'),
    ({'status':'incomplete','output':[]},'未完成'),
    ({'status':'completed','output':[message('not json')]},'不是有效 JSON'),
    ({'status':'completed','output':[message('{"size":600}')]},'缺少必填字段'),
    ({'status':'completed','output':[dict(type='message',content=[dict(type='refusal',refusal='test')])]},'拒绝'),
])
def test_plan_errors_explain_the_actual_failure(reply,match):
    client=Mock(style='responses',model='test');client.request.return_value=reply
    with pytest.raises(ValueError,match=match):plan('test',BuildSpec(),Knowledge(),client)


def test_chat_planning_rejects_truncated_json_even_if_fields_are_present():
    client=Mock(style='chat',model='test')
    client.request.return_value={'choices':[{'finish_reason':'length','message':{'content':json.dumps(plan_data())}}]}
    with pytest.raises(ValueError,match='截断'):plan('test',BuildSpec(),Knowledge(),client)


def test_restored_tool_calls_are_executed_and_kept_in_history():
    class ToolReplay(ReplayClient):
        def request(self,messages,*args,**kwargs):return super().request(messages,**kwargs)
    fn=dict(type='function_call',id='fn1',call_id='call1',namespace='cube',name='lookup_card',arguments='{"name":"Sun Titan"}')
    client=ToolReplay([[item_event(0,fn),terminal()],[item_event(0,message(json.dumps(dict(answer='已核对',swaps=[],cautions=[])))),terminal()]])
    result=advise(Catalog(),Knowledge(),BuildSpec(),[],'查看 Sun Titan',client)
    assert result['tools'][0]['name']=='lookup_card'
    output=next(x for x in client.histories[1] if x.get('type')=='function_call_output')
    assert output['call_id']=='call1' and json.loads(output['output'])['card']['name']=='Sun Titan'
