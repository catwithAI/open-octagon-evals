import pytest
from octagon_evals.models import EvaluationInput, Dimension, EvalPlan
from octagon_evals.plan import validate_plan
from octagon_evals.plan.hash import plan_hash
from octagon_evals.tasks import TaskStore, create_tasks
from octagon_evals.scorers import parse_score
from octagon_evals.errors import InvalidJudgeOutput, PlanError, StaleSubmission
from octagon_evals.aggregation import aggregate

def inp():
    return EvaluationInput("exp", "run", {"id":"s","version":1}, {"id":"t"}, {"snapshot_ref":"a","content_hash":"h"}, {"trajectory_ref":"tr"}, True)

def plan():
    return EvalPlan(1, 1, (Dimension("a", weight=.5), Dimension("b", role="diagnostic", weight=1), Dimension("h", method="human_required", weight=.5)))

def test_plan_hash_stable_and_validation():
    p = validate_plan(plan()); assert plan_hash(p) == plan_hash(p)
    with pytest.raises(PlanError): validate_plan(EvalPlan(1,1,(Dimension("x", role="diagnostic"),)))

def test_tasks_idempotent_and_lease():
    s=TaskStore(); ts=create_tasks(inp(), plan(), s); assert [t.dimension_id for t in ts] == ["a", "h"]
    assert create_tasks(inp(), plan(), s)[0] is ts[0]
    s.claim(ts[0].id); s.complete(ts[0].id)
    assert s.submit(ts[0].id, "first") == "first"

def test_invalid_score_and_aggregation():
    with pytest.raises(InvalidJudgeOutput): parse_score("t", {"value": 2}, "judge")
    score=parse_score("t", {"value": .8}, "deterministic")
    assert aggregate(plan().dimensions, {"a":score})["status"] == "pending"
    score_b=parse_score("t2", {"value": .4}, "human")
    result=aggregate(plan().dimensions, {"a":score,"h":score_b})
    assert result["status"] == "final" and result["total_score"] == pytest.approx(.6)

def test_evaluation_input_from_dict_preserves_producer_and_rejects_bad_envelope():
    value = EvaluationInput.from_dict({
        "experiment_id": "exp", "run_id": "run", "scenario": {"id": "s"},
        "task": {"id": "t"},
        "artifact": {"snapshot_ref": "snapshot://x", "content_hash": "sha256:x"},
        "history": {"trajectory_ref": "trace://x"},
        "run_status": {"upstream_completed": True},
        "producer": {"variant_id": "agent-a"},
    })
    assert value.producer["variant_id"] == "agent-a"
    with pytest.raises(ValueError):
        EvaluationInput.from_dict({"experiment_id": "exp"})
