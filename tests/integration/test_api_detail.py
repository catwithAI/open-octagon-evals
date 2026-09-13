from fastapi.testclient import TestClient
from octagon_evals.api import create_app

def test_experiment_detail_exposes_dimension_matrix(tmp_path):
    c=TestClient(create_app(str(tmp_path/"detail.db")))
    r=c.post('/experiments/e1/runs',json={'run_id':'r1','scenario':{'id':'s'},'task':{'id':'t'},'artifact':{'snapshot_ref':'a','content_hash':'h'},'history':{'trajectory_ref':'tr'},'dimensions':[{'id':'task_completion','weight':1,'method':'deterministic'}]})
    detail=c.get('/experiments/e1').json()
    assert detail['dimensions'][0]['id']=='task_completion'; assert detail['runs'][0]['dimensions'][0]['score'] is None
    tid=r.json()['task_ids'][0]; c.post('/tasks/'+tid+'/score',json={'evidence':{'checks':[True]}})
    assert c.get('/experiments/e1').json()['runs'][0]['dimensions'][0]['score']==1
