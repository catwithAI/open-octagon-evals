"""pairwise 比较评分：方法编排（对偶构建 → 裁决 → 转换）。

与 pointwise 平级；后端按 ``compare()`` 注入，方法语义留在本模块。
"""
from __future__ import annotations
from typing import Any

from .comparison import build_pairs, convert_pairwise, pair_key, validate_winner


class PairwiseScorer:
    def __init__(self, backend):
        self.backend = backend

    def run(self, task, dimension, evidence_by_run: dict[str, Any], config, existing=None):
        """对 experiment 的 run 两两比较，返回 (comparisons, scores)。

        ``existing``: {pair_key: {"winner": winner_id, ...}}，已持久化的裁决；
        命中的 pair 直接复用，不重新采样。

        comparisons: 规范序 (a<b) 的裁决记录，winner 是实际胜者 run id 或 'tie'，
        与呈现顺序无关，可直接持久化。
        scores: {run_id: float | None}，None 表示该 run 没有被任何比较采样。
        """
        existing = existing or {}
        run_ids = sorted(evidence_by_run)
        question = dimension.question or dimension.id
        comparisons: list[dict[str, Any]] = []
        for a, b in build_pairs(run_ids, config.strategy, config.max_pairs, seed=task.plan_hash):
            pkey = pair_key(task.id, a, b)
            prior = existing.get(pkey)
            if prior is not None:
                winner_id = prior.get("winner")
                reason = prior.get("reason")
                raw = prior.get("raw")
            else:
                candidates = [
                    {"id": a, "evidence": evidence_by_run[a]},
                    {"id": b, "evidence": evidence_by_run[b]},
                ]
                verdict = self.backend.compare(
                    pkey, candidates, question,
                    anchors=dimension.anchors,
                    allow_ties=config.allow_ties,
                )
                # 方法语义：这里独立校验 winner，不依赖后端是否已校验。
                winner = validate_winner(verdict, a, b, allow_ties=config.allow_ties)
                # 归一化为规范序下的胜者 id：不随呈现顺序变化。
                winner_id = "tie" if winner == "tie" else (a if winner == "a" else b)
                reason = verdict.get("reason")
                raw = verdict.get("raw")
            canonical = sorted((a, b))
            comparisons.append({
                "a": canonical[0],
                "b": canonical[1],
                "winner": winner_id,
                "reason": reason,
                "raw": raw,
                "pair_key": pkey,
                # judge 实际看到的呈现顺序，持久化时保留以便审计。
                "presented": [a, b],
            })
        scores = convert_pairwise(comparisons, run_ids, config.conversion)
        return comparisons, scores
