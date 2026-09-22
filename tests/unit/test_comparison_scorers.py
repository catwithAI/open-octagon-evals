"""PairwiseScorer / ListwiseScorer 编排：对偶构建、裁决归一化、复用、转换。"""
import pytest

from octagon_evals.errors import InvalidJudgeOutput, PlanError
from octagon_evals.models import ComparisonConfig, Dimension, EvalPlan
from octagon_evals.scorers.pairwise import PairwiseScorer
from octagon_evals.scorers.listwise import ListwiseScorer


class FakeBackend:
    """脚本化后端：记录被调用的 pair/rank task_id，按规范对偶返回裁决。"""

    def __init__(self, verdicts, rank_output=None):
        # verdicts: {规范序对偶 (a,b): 胜者 run id 或 'tie'}，与呈现顺序无关
        self.verdicts = verdicts
        self.rank_output = rank_output
        self.called = []
        self.comparisons = []
        self.ranks = []

    def compare(self, task_id, candidates, question, *, anchors=None, allow_ties=True, output_schema=None):
        self.called.append(task_id)
        self.comparisons.append((task_id, candidates, question))
        key = tuple(sorted(c["id"] for c in candidates))
        return {"winner": self.verdicts.get(key, "tie"), "reason": "decided", "raw": {}}

    def rank(self, task_id, candidates, question, *, anchors=None, output_schema=None):
        self.called.append(task_id)
        self.ranks.append((task_id, candidates, question))
        return {"ranking": self.rank_output, "reason": "ordered", "raw": {}}


def _dim(method, **overrides):
    return Dimension("quality", method=method, question="Which is better?",
                     comparison=ComparisonConfig(**overrides))


def _task():
    return type("T", (), {"id": "e1:ph:quality", "plan_hash": "ph"})()


def test_pairwise_round_robin_converts_and_uses_canonical_keys():
    backend = FakeBackend({
        ("run-a", "run-b"): "run-a",
        ("run-a", "run-c"): "run-a",
        ("run-b", "run-c"): "run-b",
    })
    scorer = PairwiseScorer(backend)
    evidence = {"run-a": {"x": 1}, "run-b": {"x": 0}, "run-c": {"x": 0}}
    comparisons, scores = scorer.run(_task(), _dim("pairwise_judge"), evidence, ComparisonConfig())
    assert len(backend.called) == 3
    assert scores == {"run-a": 1.0, "run-b": 0.5, "run-c": 0.0}
    # pair key 用规范序，即使 backend 收到的是被翻转的呈现顺序。
    assert {c["pair_key"] for c in comparisons} == {
        "e1:ph:quality:run-a_vs_run-b",
        "e1:ph:quality:run-a_vs_run-c",
        "e1:ph:quality:run-b_vs_run-c",
    }


def test_pairwise_reuses_existing_verdicts_without_resampling():
    backend = FakeBackend({
        ("run-a", "run-c"): "run-a",
        ("run-b", "run-c"): "run-b",
    })
    scorer = PairwiseScorer(backend)
    evidence = {"run-a": {"x": 1}, "run-b": {"x": 0}, "run-c": {"x": 0}}
    existing = {
        "e1:ph:quality:run-a_vs_run-b": {"winner": "run-a", "reason": "prior", "raw": {}},
    }
    comparisons, scores = scorer.run(_task(), _dim("pairwise_judge"), evidence, ComparisonConfig(), existing=existing)
    # 只有新 pair 触发后端调用。
    assert backend.called == ["e1:ph:quality:run-a_vs_run-c", "e1:ph:quality:run-b_vs_run-c"]
    assert scores["run-a"] == 1.0


def test_pairwise_sampled_limits_pairs():
    backend = FakeBackend({})
    scorer = PairwiseScorer(backend)
    evidence = {f"run-{i}": {"x": i} for i in range(6)}
    comparisons, scores = scorer.run(
        _task(), _dim("pairwise_judge"), evidence, ComparisonConfig(strategy="sampled", max_pairs=4)
    )
    assert len(comparisons) == 4 < 15  # 全量是 15 对，采样只取 4 对
    assert len(backend.called) == 4
    assert all(v == 0.5 for v in scores.values() if v is not None)


def test_pairwise_sampled_can_leave_a_run_without_score():
    backend = FakeBackend({})
    scorer = PairwiseScorer(backend)
    evidence = {f"run-{i}": {"x": i} for i in range(6)}
    comparisons, scores = scorer.run(
        _task(), _dim("pairwise_judge"), evidence, ComparisonConfig(strategy="sampled", max_pairs=1)
    )
    assert len(comparisons) == 1
    assert sum(v is None for v in scores.values()) == 4  # 只有 1 对被采样


def test_listwise_single_rank_and_conversion():
    backend = FakeBackend({}, rank_output=["run-b", "run-a", "run-c"])
    scorer = ListwiseScorer(backend)
    evidence = {"run-a": {"x": 1}, "run-b": {"x": 1}, "run-c": {"x": 1}}
    verdict, scores = scorer.run(_task(), _dim("listwise_judge"), evidence, ComparisonConfig())
    assert backend.called == ["e1:ph:quality:rank"]
    assert scores == {"run-a": 0.5, "run-b": 1.0, "run-c": 0.0}
    assert verdict["ranking"] == ["run-b", "run-a", "run-c"]


def test_listwise_enforces_max_candidates():
    backend = FakeBackend({}, rank_output=["run-a", "run-b"])
    scorer = ListwiseScorer(backend)
    evidence = {f"run-{i}": {"x": i} for i in range(3)}
    with pytest.raises(PlanError):
        scorer.run(_task(), _dim("listwise_judge"), evidence, ComparisonConfig(max_candidates=2))


def test_listwise_reuses_existing_ranking():
    backend = FakeBackend({}, rank_output=["run-a", "run-b", "run-c"])
    scorer = ListwiseScorer(backend)
    evidence = {"run-a": {}, "run-b": {}, "run-c": {}}
    verdict, scores = scorer.run(
        _task(), _dim("listwise_judge"), evidence, ComparisonConfig(),
        existing={"e1:ph:quality:rank": {"ranking": ["run-c", "run-b", "run-a"]}},
    )
    assert backend.called == []  # 复用，不重新采样
    assert scores == {"run-a": 0.0, "run-b": 0.5, "run-c": 1.0}


def test_backend_winner_validation_failure_propagates():
    backend = FakeBackend({("run-a", "run-b"): "run-x"})  # 非法胜者
    scorer = PairwiseScorer(backend)
    with pytest.raises(InvalidJudgeOutput):
        scorer.run(_task(), _dim("pairwise_judge"), {"run-a": {}, "run-b": {}}, ComparisonConfig())
