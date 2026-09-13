from octagon_evals.db import SQLiteStore
from octagon_evals.models import EvaluationInput, EvalPlan, Dimension
from octagon_evals.scorers.deterministic import default_registry
from octagon_evals.service import EvaluationService
from octagon_evals.worker import DeterministicWorker

def test_service_and_worker_run_sqlite_pipeline(tmp_path):
    plan=EvalPlan(1,1,(Dimension("task_completion",weight=1),),plan_hash="sha256:plan")
    inp=EvaluationInput("e","r",{"id":"scene"},{"id":"task"},{"snapshot_ref":"a","content_hash":"h"},{"trajectory_ref":"t"},True)
    db=SQLiteStore(tmp_path/"pipeline.db"); service=EvaluationService(db=db,registry=default_registry()); tasks=service.start(inp,plan)
    done=DeterministicWorker(service,plan,{tasks[0].id:{"checks":[True,False]}}).run_once()
    assert done == [tasks[0].id]; assert service.total(plan, "r")["total_score"] == .5
    assert db.get_task(tasks[0].id).state == "completed"
