"""listwise 比较评分：方法编排（整体排序 → 转换）。

与 pointwise 平级；后端按 ``rank()`` 注入，方法语义留在本模块。
"""
from __future__ import annotations
from typing import Any

from ..errors import PlanError
from .comparison import convert_rank_interpolation


class ListwiseScorer:
    def __init__(self, backend):
        self.backend = backend

    def run(self, task, dimension, evidence_by_run: dict[str, Any], config, existing=None):
        """对 experiment 的全部 run 一次性排序，返回 (verdict, scores)。

        ``existing``: {rank_key: {"ranking": [...], ...}}，已持久化的裁决；
        命中则直接复用，不重新采样。
        """
        run_ids = sorted(evidence_by_run)
        if config.max_candidates and len(run_ids) > config.max_candidates:
            raise PlanError(
                f"listwise dimension {dimension.id} has {len(run_ids)} candidates, "
                f"exceeds max_candidates={config.max_candidates}"
            )
        question = dimension.question or dimension.id
        rank_key = f"{task.id}:rank"
        prior = (existing or {}).get(rank_key)
        if prior is not None:
            verdict = {"ranking": prior.get("ranking"), "reason": prior.get("reason"), "raw": prior.get("raw")}
        else:
            candidates = [{"id": rid, "evidence": evidence_by_run[rid]} for rid in run_ids]
            verdict = self.backend.rank(rank_key, candidates, question, anchors=dimension.anchors)
        scores = convert_rank_interpolation(verdict["ranking"], run_ids)
        return verdict, scores
