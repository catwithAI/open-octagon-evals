import pytest
from octagon_evals.models import DimensionTask
from octagon_evals.scorers.registry import ScorerRegistry, ScorerSpec
from octagon_evals.scorers.runner import ScorerRunner

def test_runner_invokes_registered_checker_once():
    reg=ScorerRegistry(); reg.register(ScorerSpec("done","deterministic","1","sha256:x",lambda e:{"value":1}))
    runner=ScorerRunner(reg); task=DimensionTask("t","e","r","p","done","deterministic")
    assert runner.run(task, {}) .value == 1
    with pytest.raises(RuntimeError): runner.run(task, {})

def test_runner_allows_retry_after_handler_failure():
    outputs=iter([RuntimeError("flaky"),{"value":1}])
    def handler(evidence):
        output=next(outputs)
        if isinstance(output, Exception): raise output
        return output
    reg=ScorerRegistry(); reg.register(ScorerSpec("done","deterministic","1","sha256:x",handler))
    runner=ScorerRunner(reg); task=DimensionTask("t","e","r","p","done","deterministic")
    with pytest.raises(RuntimeError): runner.run(task, {})
    assert runner.run(task, {}).value == 1
