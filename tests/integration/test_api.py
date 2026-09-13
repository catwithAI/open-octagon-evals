from fastapi.testclient import TestClient
from octagon_evals.api import create_app

def _run_payload(run_id, dimensions=None):
    return {"run_id":run_id,"scenario":{"id":"s","version":1},"task":{"id":"t"},"artifact":{"snapshot_ref":"a","content_hash":"h"},"history":{"trajectory_ref":"tr"},"dimensions":dimensions or [{"id":"task_completion","weight":1,"method":"deterministic"}]}

def test_fastapi_mvp_flow(tmp_path):
    client=TestClient(create_app(str(tmp_path/"api.db")))
    response=client.post("/experiments/e1/runs",json=_run_payload("r1"))
    assert response.status_code == 201
    task_id=response.json()["task_ids"][0]
    assert client.post(f"/tasks/{task_id}/score",json={"evidence":{"checks":[True,False]}}).json()["value"] == .5
    assert client.get("/experiments/e1/score").json()["runs"]["r1"]["total_score"] == .5

def test_experiment_score_is_per_run(tmp_path):
    client=TestClient(create_app(str(tmp_path/"api.db")))
    task_ids={run_id:client.post("/experiments/e1/runs",json=_run_payload(run_id)).json()["task_ids"][0] for run_id in ("r1","r2")}
    client.post(f"/tasks/{task_ids['r1']}/score",json={"evidence":{"checks":[True,True]}})
    client.post(f"/tasks/{task_ids['r2']}/score",json={"evidence":{"checks":[True,False]}})
    runs=client.get("/experiments/e1/score").json()["runs"]
    assert runs["r1"]["total_score"] == 1 and runs["r2"]["total_score"] == .5

def test_second_run_with_different_plan_is_rejected(tmp_path):
    client=TestClient(create_app(str(tmp_path/"api.db")))
    assert client.post("/experiments/e1/runs",json=_run_payload("r1")).status_code == 201
    response=client.post("/experiments/e1/runs",json=_run_payload("r2",[{"id":"task_completion","weight":0.5,"method":"deterministic"}]))
    assert response.status_code == 409
