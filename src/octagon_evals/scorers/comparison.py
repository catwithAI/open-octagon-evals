"""比较式评分的确定性核心：对偶构建、裁决校验、标量转换。

这些函数不调用 judge，不接触存储；输入要么来自计划配置，要么来自
持久化的比较原语。转换结果版本化，禁止从重采样结果反推。
"""
from __future__ import annotations
import hashlib
import random
from typing import Any

from ..errors import InvalidJudgeOutput, PlanError

_WIN_COUNT = "win_count"
_BRADLEY_TERRY = "bradley_terry"
_RANK_INTERPOLATION = "rank_interpolation"


def pair_key(task_id: str, run_a: str, run_b: str) -> str:
    """pair 的规范去重键：不随呈现顺序变化。"""
    a, b = sorted((run_a, run_b))
    return f"{task_id}:{a}_vs_{b}"


def build_pairs(run_ids, strategy: str = "round_robin", max_pairs: int = 0, seed: str | None = None):
    """按策略构建 (a, b) 对偶，呈现顺序用种子确定性随机化。

    随机化缓解 LLM judge 的位置偏差；种子=plan_hash，同一实验结果可复现。
    winner 以候选 id 表示，与呈现顺序无关，因此翻转顺序不影响裁决语义。
    """
    run_ids = sorted(run_ids)
    all_pairs = [(a, b) for i, a in enumerate(run_ids) for b in run_ids[i + 1:]]
    if strategy == "sampled" and max_pairs and max_pairs < len(all_pairs):
        all_pairs = random.Random(seed).sample(all_pairs, max_pairs)
    elif strategy != "round_robin":
        raise PlanError(f"unknown comparison strategy: {strategy}")
    rng = random.Random(seed)
    return [(pair if rng.random() < 0.5 else (pair[1], pair[0])) for pair in all_pairs]


def validate_winner(output: dict[str, Any], run_a: str, run_b: str, *, allow_ties: bool = True) -> str:
    """校验 compare 裁决的 winner，返回归一化的 'a' | 'b' | 'tie'。"""
    winner = output.get("winner")
    ids = {run_a, run_b}
    if winner == run_a:
        return "a"
    if winner == run_b:
        return "b"
    if winner == "tie":
        if not allow_ties:
            raise InvalidJudgeOutput("tie not allowed for this comparison")
        return "tie"
    raise InvalidJudgeOutput(f"invalid winner {winner!r}: must be one of {sorted(ids)} or 'tie'")


def validate_ranking(output: dict[str, Any], run_ids) -> list[str]:
    """校验 rank 裁决的 ranking 是 run_ids 的一个严格全排列。"""
    ranking = output.get("ranking")
    if not isinstance(ranking, list):
        raise InvalidJudgeOutput("ranking must be an array of candidate ids")
    expected = sorted(run_ids)
    if sorted(ranking) != expected or len(set(ranking)) != len(ranking):
        raise InvalidJudgeOutput(
            f"ranking must be a permutation of {expected} (got {ranking!r})"
        )
    return ranking


def convert_pairwise(comparisons: list[dict[str, Any]], run_ids, conversion: str = _WIN_COUNT) -> dict[str, float | None]:
    """把 pair 裁决列表转成每-run 标量。

    comparisons: [{"a": rid, "b": rid, "winner": rid 或 "tie"}, ...]
    ``a``/``b`` 是规范序（a < b），``winner`` 是实际胜者的 run id 或 "tie"，
    因此与呈现顺序无关。返回 {run_id: score | None}；完全没被采样的 run 为
    None（该维度无分数）。
    """
    if conversion == _BRADLEY_TERRY:
        return _convert_bradley_terry(comparisons, run_ids)
    return _convert_win_count(comparisons, run_ids)


def convert_rank_interpolation(ranking: list[str], run_ids) -> dict[str, float | None]:
    """listwise 名次 → 每-run 标量。K=1 → 1.0；K=0（不可能，由校验保证）→ None。"""
    scores: dict[str, float | None] = {r: None for r in run_ids}
    k = len(ranking)
    if k == 0:
        return scores
    if k == 1:
        scores[ranking[0]] = 1.0
        return scores
    for idx, rid in enumerate(ranking):
        scores[rid] = 1.0 - idx / (k - 1)
    return scores


def _convert_win_count(comparisons, run_ids) -> dict[str, float | None]:
    won = {r: 0.0 for r in run_ids}
    seen = {r: 0 for r in run_ids}
    for c in comparisons:
        a, b = c["a"], c["b"]
        winner = c.get("winner")
        if a not in seen or b not in seen:
            raise InvalidJudgeOutput("comparison references an unknown run")
        seen[a] += 1
        seen[b] += 1
        if winner == a:
            won[a] += 1.0
        elif winner == b:
            won[b] += 1.0
        else:
            won[a] += 0.5
            won[b] += 0.5
    return {r: (won[r] / seen[r] if seen[r] else None) for r in run_ids}


def _convert_bradley_terry(comparisons, run_ids, iterations: int = 100) -> dict[str, float | None]:
    """Bradley-Terry 强度估计，按最大强度归一化到 [0,1]。

    标准 MM 更新：s_a = W_a / Σ_b n_ab/(s_a+s_b)，W_a 记平局为 0.5 胜。
    comparisons 缺失（n_ab=0）的 run 无分数，返回 None。
    """
    wins = {a: {b: 0.0 for b in run_ids} for a in run_ids}
    counts = {a: {b: 0 for b in run_ids} for a in run_ids}
    for c in comparisons:
        a, b = c["a"], c["b"]
        winner = c.get("winner")
        if a not in wins or b not in wins:
            raise InvalidJudgeOutput("comparison references an unknown run")
        counts[a][b] += 1
        counts[b][a] += 1
        if winner == a:
            wins[a][b] += 1.0
        elif winner == b:
            wins[b][a] += 1.0
        else:
            wins[a][b] += 0.5
            wins[b][a] += 0.5

    strengths = {r: 1.0 for r in run_ids}
    for _ in range(iterations):
        nxt: dict[str, float] = {}
        for a in run_ids:
            win_sum = sum(wins[a][b] for b in run_ids)
            denominator = sum(
                counts[a][b] / (strengths[a] + strengths[b])
                for b in run_ids if counts[a][b] > 0
            )
            nxt[a] = win_sum / denominator if denominator > 0 else strengths[a]
        strengths = nxt

    maximum = max(strengths.values())
    if maximum <= 0:
        return {r: None for r in run_ids}
    return {r: (strengths[r] / maximum if sum(counts[r].values()) else None) for r in run_ids}
