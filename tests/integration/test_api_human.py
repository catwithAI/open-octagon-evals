from fastapi.testclient import TestClient
from octagon_evals.api import create_app

def test_human_api_is_idempotent_and_validates_reviewer(tmp_path):
    c=TestClient(create_app(str(tmp_path/"human-api.db")))
    r=c.post('/experiments/e1/runs',json={'run_id':'r1','scenario':{'id':'s'},'task':{'id':'t'},'artifact':{'snapshot_ref':'a','content_hash':'h'},'history':{'trajectory_ref':'tr'},'dimensions':[{'id':'quality','weight':1,'method':'human_required'}]})
    tid=r.json()['task_ids'][0]; assert c.post('/human-tasks/'+tid).status_code==201
    assert c.post('/human-tasks/'+tid+'/assign?reviewer_id=rev').status_code==200
    assert c.post('/human-tasks/'+tid+'/submit',json={'reviewer_id':'bad','value':.2}).status_code==409
    first=c.post('/human-tasks/'+tid+'/submit',json={'reviewer_id':'rev','value':.8}); second=c.post('/human-tasks/'+tid+'/submit',json={'reviewer_id':'rev','value':.1})
    assert first.json()['value']==second.json()['value']==.8
