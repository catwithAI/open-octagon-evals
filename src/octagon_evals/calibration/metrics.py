"""校准指标：ACC / ValidACC / 分组 ACC / Wilson 95% 置信区间。

口径与 rubricbench ``eval_submission.py::evaluate`` 一致（invalid 按错计，
ACC = correct / total；ValidACC = correct / parsed）。每个 ACC 带 Wilson
置信区间，抽样报告据此判断 judge 可信度的范围。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

GROUP_ORDER = ["IF", "STEM", "CODE", "SAFE", "CHAT"]


def wilson_ci(correct: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval（默认 95%），裁剪到 [0, 1]。n=0 返回 (nan, nan)。"""
    if n <= 0:
        return (float("nan"), float("nan"))
    p = correct / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


@dataclass(frozen=True)
class GroupMetric:
    group: str  # "IF" / "STEM" / ... / "Overall"
    total: int
    correct: int
    valid: int
    invalid: int
    acc: float
    valid_acc: float
    ci_lo: float
    ci_hi: float

    @classmethod
    def from_records(cls, group: str, records) -> "GroupMetric":
        total = len(records)
        valid = sum(1 for r in records if r["verdict"] is not None)
        correct = sum(1 for r in records if r["verdict"] == r["gold"])
        invalid = total - valid
        acc = correct / total if total else 0.0
        valid_acc = correct / valid if valid else 0.0
        lo, hi = wilson_ci(correct, total)
        return cls(group, total, correct, valid, invalid, acc, valid_acc, lo, hi)


def aggregate(records, groups: list[str] | None = None) -> list[GroupMetric]:
    """把裁决记录聚合成指标行：Overall + 每个有样本的分组（按 GROUP_ORDER）。

    记录为 dict，需含 ``group`` / ``verdict``（None = invalid）/ ``gold``。
    """
    by_group: dict[str, list] = {}
    for rec in records:
        by_group.setdefault(rec.get("group"), []).append(rec)
    groups = groups or GROUP_ORDER
    rows = [GroupMetric.from_records(g, by_group.get(g, [])) for g in groups if by_group.get(g)]
    rows.insert(0, GroupMetric.from_records("Overall", records))
    return rows
