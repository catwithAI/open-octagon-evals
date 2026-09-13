from octagon_evals.scorers.deterministic import default_registry, task_completion, dangerous_action_confirmation
from octagon_evals.scorers.runner import ScorerRunner
from octagon_evals.models import DimensionTask

def test_completion_checker_uses_evidence_checks():
    assert task_completion({"checks": [{"passed": True}, {"passed": False}, True]})["value"] == 2/3

def test_dangerous_action_requires_confirmation():
    assert dangerous_action_confirmation({})["value"] == 1
    assert dangerous_action_confirmation({"dangerous_actions": [{"executed": True, "confirmed": False}]})["value"] == 0

def test_default_registry_runs_builtin_checker():
    task=DimensionTask("t","e","r","p","task_completion","deterministic")
    score=ScorerRunner(default_registry()).run(task, {"checks": [True, True]})
    assert score.value == 1 and score.lineage["source_hash"].startswith("builtin:")
