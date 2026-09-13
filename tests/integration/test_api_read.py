from fastapi.testclient import TestClient
from octagon_evals.api import create_app

def test_experiment_list_and_task_detail(tmp_path):
    path=str(tmp_path/"read.db"); c=TestClient(create_app(path))
    r=c.post('/experiments/e1/runs',json={'run_id':'r1','scenario':{'id':'s','version':1},'task':{'id':'t'},'artifact':{'snapshot_ref':'a','content_hash':'h'},'history':{'trajectory_ref':'tr'},'dimensions':[{'id':'task_completion','weight':1,'method':'deterministic'}]})
    tid=r.json()['task_ids'][0]
    assert c.get('/experiments').json()[0]['run_count']==1
    assert c.get('/tasks/'+tid).json()['state']=='queued'

def test_score_read_after_app_restart(tmp_path):
    path=str(tmp_path/"restart.db"); c=TestClient(create_app(path))
    r=c.post('/experiments/e1/runs',json={'run_id':'r1','scenario':{'id':'s','version':1},'task':{'id':'t'},'artifact':{'snapshot_ref':'a','content_hash':'h'},'history':{'trajectory_ref':'tr'},'dimensions':[{'id':'task_completion','weight':1,'method':'deterministic'}]})
    tid=r.json()['task_ids'][0]; c.post('/tasks/'+tid+'/score',json={'evidence':{'checks':[True]}})
    restarted=TestClient(create_app(path)); result=restarted.get('/experiments/e1/score').json()
    assert result['runs']['r1']['total_score'] == 1

def test_api_allows_static_console_cross_origin_requests(tmp_path):
    c = TestClient(create_app(str(tmp_path / "cors.db")))
    response = c.options(
        "/experiments",
        headers={
            "Origin": "http://127.0.0.1:5180",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"
