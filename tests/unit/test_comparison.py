"""比较式评分的确定性核心：对偶、校验、转换。"""
import pytest

from octagon_evals.errors import InvalidJudgeOutput
from octagon_evals.scorers.comparison import (
    build_pairs,
    convert_pairwise,
    convert_rank_interpolation,
    pair_key,
    validate_ranking,
    validate_winner,
)


def test_pair_key_is_canonical_regardless_of_order():
    assert pair_key("t", "run-b", "run-a") == pair_key("t", "run-a", "run-b")
    assert pair_key("t", "run-a", "run-b") == "t:run-a_vs_run-b"


def test_build_pairs_round_robin_covers_every_pair():
    pairs = build_pairs(["run-c", "run-a", "run-b"], "round_robin")
    assert {frozenset(p) for p in pairs} == {
        frozenset(("run-a", "run-b")),
        frozenset(("run-a", "run-c")),
        frozenset(("run-b", "run-c")),
    }


def test_build_pairs_is_deterministic_and_position_randomized():
    first = build_pairs(["a", "b", "c", "d"], "round_robin", seed="plan-hash")
    second = build_pairs(["a", "b", "c", "d"], "round_robin", seed="plan-hash")
    assert first == second
    assert any(p[0] > p[1] for p in first)  # 呈现顺序并非总是字典序


def test_build_pairs_sampled_respects_max_pairs_and_seed():
    pairs = build_pairs(["a", "b", "c", "d", "e"], "sampled", max_pairs=4, seed="plan-hash")
    assert len(pairs) == 4
    assert build_pairs(["a", "b", "c", "d", "e"], "sampled", max_pairs=4, seed="plan-hash") == pairs


def test_validate_winner_accepts_ids_and_tie():
    assert validate_winner({"winner": "run-a"}, "run-a", "run-b") == "a"
    assert validate_winner({"winner": "run-b"}, "run-a", "run-b") == "b"
    assert validate_winner({"winner": "tie"}, "run-a", "run-b") == "tie"


def test_validate_winner_rejects_unknown_and_forbidden_tie():
    with pytest.raises(InvalidJudgeOutput):
        validate_winner({"winner": "run-x"}, "run-a", "run-b")
    with pytest.raises(InvalidJudgeOutput):
        validate_winner({"winner": "tie"}, "run-a", "run-b", allow_ties=False)


def test_validate_ranking_requires_full_permutation():
    assert validate_ranking({"ranking": ["run-b", "run-a"]}, ["run-a", "run-b"]) == ["run-b", "run-a"]
    with pytest.raises(InvalidJudgeOutput):
        validate_ranking({"ranking": ["run-a"]}, ["run-a", "run-b"])  # 缺
    with pytest.raises(InvalidJudgeOutput):
        validate_ranking({"ranking": ["run-a", "run-a"]}, ["run-a", "run-b"])  # 重
    with pytest.raises(InvalidJudgeOutput):
        validate_ranking({"ranking": ["run-a", "run-b", "run-c"]}, ["run-a", "run-b"])  # 多
    with pytest.raises(InvalidJudgeOutput):
        validate_ranking({"ranking": "not-a-list"}, ["run-a", "run-b"])


def test_win_count_dominance_and_ties():
    comparisons = [
        {"a": "run-a", "b": "run-b", "winner": "run-a"},
        {"a": "run-a", "b": "run-c", "winner": "run-a"},
        {"a": "run-b", "b": "run-c", "winner": "run-b"},
    ]
    scores = convert_pairwise(comparisons, ["run-a", "run-b", "run-c"], "win_count")
    assert scores == {"run-a": 1.0, "run-b": 0.5, "run-c": 0.0}

    tied = convert_pairwise([{"a": "run-a", "b": "run-b", "winner": "tie"}], ["run-a", "run-b"], "win_count")
    assert tied == {"run-a": 0.5, "run-b": 0.5}


def test_win_count_marks_unsampled_run_as_none():
    scores = convert_pairwise(
        [{"a": "run-a", "b": "run-b", "winner": "run-a"}],
        ["run-a", "run-b", "run-c"],
        "win_count",
    )
    assert scores["run-c"] is None
    assert scores["run-a"] == 1.0


def test_bradley_terry_recovers_strength_order():
    comparisons = [
        {"a": "run-a", "b": "run-b", "winner": "run-a"},
        {"a": "run-b", "b": "run-c", "winner": "run-b"},
    ]
    scores = convert_pairwise(comparisons, ["run-a", "run-b", "run-c"], "bradley_terry")
    assert scores["run-a"] == pytest.approx(1.0)
    assert scores["run-b"] < 1.0 and scores["run-b"] > 0.0
    assert scores["run-c"] == pytest.approx(0.0)


def test_bradley_terry_all_tie_is_indistinguishable():
    comparisons = [
        {"a": "run-a", "b": "run-b", "winner": "tie"},
        {"a": "run-a", "b": "run-c", "winner": "tie"},
        {"a": "run-b", "b": "run-c", "winner": "tie"},
    ]
    scores = convert_pairwise(comparisons, ["run-a", "run-b", "run-c"], "bradley_terry")
    assert scores["run-a"] == pytest.approx(1.0)
    assert scores["run-b"] == pytest.approx(1.0)
    assert scores["run-c"] == pytest.approx(1.0)


def test_rank_interpolation_spreads_ranks_to_unit_interval():
    scores = convert_rank_interpolation(["run-b", "run-a", "run-c"], ["run-a", "run-b", "run-c"])
    assert scores == {"run-a": 0.5, "run-b": 1.0, "run-c": 0.0}
    assert convert_rank_interpolation(["run-a"], ["run-a"]) == {"run-a": 1.0}


def test_convert_pairwise_rejects_unknown_run():
    with pytest.raises(InvalidJudgeOutput):
        convert_pairwise([{"a": "run-a", "b": "run-x", "winner": "run-a"}], ["run-a"], "win_count")


# --- plan 校验：比较维度的 conversion 约束 ---

from octagon_evals.errors import PlanError
from octagon_evals.models import ComparisonConfig, Dimension, EvalPlan
from octagon_evals.plan.validator import validate_plan


def _plan(dim):
    return EvalPlan(1, 1, (dim,))


def test_listwise_accepts_default_conversion_as_placeholder():
    dim = Dimension("quality", method="listwise_judge", comparison=ComparisonConfig(max_candidates=8))
    assert validate_plan(_plan(dim)) is not None


def test_pairwise_rejects_listwise_only_conversion():
    dim = Dimension("quality", method="pairwise_judge", comparison=ComparisonConfig(conversion="rank_interpolation"))
    with pytest.raises(PlanError):
        validate_plan(_plan(dim))


def test_listwise_rejects_explicit_non_rank_conversion():
    dim = Dimension("quality", method="listwise_judge", comparison=ComparisonConfig(conversion="bradley_terry"))
    with pytest.raises(PlanError):
        validate_plan(_plan(dim))
