import pytest
from octagon_evals.models import EvaluationInput
from octagon_evals.plan.loader import load_plan
from octagon_evals.tasks import TaskStore, create_tasks
from octagon_evals.scores.service import ScoreStore
from octagon_evals.aggregation import aggregate

def test_full_mvp_pipeline():
    plan=load_plan({"eval":{"schema_version":1,"plan":{"version":1,"dimensions":[
        {"id":"completion","role":"scored","weight":.6,"method":"deterministic"},
        {"id":"quality","role":"scored","weight":.4,"method":"human_required"},
        {"id":"trace","role":"diagnostic","weight":1,"method":"deterministic"}]}}})
    inp=EvaluationInput("exp","run",{"id":"scene","version":1},{"id":"task"},{"snapshot_ref":"s","content_hash":"sha256:x"},{"trajectory_ref":"t"},True)
    tasks=create_tasks(inp,plan,TaskStore()); store=ScoreStore()
    scores={t.dimension_id:store.record(t,{"value": .8 if t.dimension_id=="completion" else .5},t.method) for t in tasks}
    result=aggregate(plan.dimensions,scores,plan_hash=plan.plan_hash)
    assert result["status"]=="final" and result["total_score"]==pytest.approx(.68) and result["plan_hash"]==plan.plan_hash
