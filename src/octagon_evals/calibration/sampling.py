"""抽样校准：从 RubricBench case 里选一批来判。

全量 1147 个 pair 跑 judge 成本过高，默认分层抽样：

- ``stratified``：按分组大小做 Hamilton（最大余数）分配预算到各组，组内按
  label 均衡选取，固定 ``random.Random(seed)`` 保证可复现；
- ``random``：全局洗牌取前 limit 个；
- ``full``：全量（忽略 limit）。

limit 达到或超过可用量时自动转全量。返回 ``SamplePlan`` 记录分配与是否全量，
供报告透明展示（组内 judged/available）。
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from .rubricbench import RubricCase


@dataclass(frozen=True)
class SamplePlan:
    strategy: str
    limit: int
    seed: int
    allocation: dict[str, int] = field(default_factory=dict)
    is_full: bool = False
    total_available: int = 0


def _balance_select(cases: list[RubricCase], budget: int, rng: random.Random) -> list[RubricCase]:
    """组内按 label 均衡选 budget 个：从大池先取、两池交替，耗尽回退到另一池。"""
    if budget >= len(cases):
        return list(cases)
    pools = {label: [c for c in cases if c.label == label] for label in (0, 1)}
    for pool in pools.values():
        rng.shuffle(pool)
    bigger, smaller = (0, 1) if len(pools[0]) >= len(pools[1]) else (1, 0)
    result: list[RubricCase] = []
    bi = si = 0
    while len(result) < budget:
        if len(result) % 2 == 0:
            if bi < len(pools[bigger]):
                result.append(pools[bigger][bi]); bi += 1
            elif si < len(pools[smaller]):
                result.append(pools[smaller][si]); si += 1
            else:
                break
        else:
            if si < len(pools[smaller]):
                result.append(pools[smaller][si]); si += 1
            elif bi < len(pools[bigger]):
                result.append(pools[bigger][bi]); bi += 1
            else:
                break
    return result


def _allocate_hamilton(group_sizes: dict[str, int], limit: int) -> dict[str, int]:
    """Hamilton 最大余数法：按组大小比例分配 limit，整数下取整 + 最大余数补足。"""
    groups = [g for g, n in group_sizes.items() if n > 0]
    total = sum(group_sizes[g] for g in groups)
    if not groups or total == 0:
        return {}
    if limit >= total:
        return {g: group_sizes[g] for g in groups}
    alloc: dict[str, int] = {}
    remainder: dict[str, float] = {}
    for g in groups:
        exact = group_sizes[g] * limit / total
        floor = int(exact)
        alloc[g] = floor
        remainder[g] = exact - floor
    remaining = limit - sum(alloc.values())
    # 最大余数优先补 1，但不能超过该组可用量。
    for g in sorted(groups, key=lambda g: -remainder[g]):
        if remaining <= 0:
            break
        if alloc[g] < group_sizes[g]:
            alloc[g] += 1
            remaining -= 1
    # 仍有剩余（各组都到顶）时顺序回填其余组，不应发生（limit < total）。
    if remaining > 0:
        for g in groups:
            if remaining <= 0:
                break
            headroom = group_sizes[g] - alloc[g]
            take = min(headroom, remaining)
            alloc[g] += take
            remaining -= take
    return alloc


def sample_cases(
    cases: list[RubricCase],
    *,
    strategy: str = "stratified",
    limit: int = 100,
    seed: int = 1,
    groups: set[str] | None = None,
) -> tuple[list[RubricCase], SamplePlan]:
    """按策略选一批 case。``groups`` 为分组选择器集合（如 {"code","chat"}）。

    返回 (selected, plan)。``plan`` 携带分配表与是否全量；选中项按 case_id 排序。
    """
    strategy = strategy or "stratified"
    if groups:
        cases = [c for c in cases if c.group in groups]
    by_group: dict[str, list[RubricCase]] = {}
    for c in cases:
        if c.group is not None:
            by_group.setdefault(c.group, []).append(c)
    total_available = len(cases)

    if strategy == "full" or limit >= total_available:
        selected = [c for c in cases]
        allocation = {g: len(v) for g, v in by_group.items()}
        return selected, SamplePlan("full" if limit >= total_available else strategy, limit, seed, allocation, is_full=True, total_available=total_available)

    rng = random.Random(seed)
    if strategy == "random":
        pool = list(cases)
        rng.shuffle(pool)
        chosen = pool[:limit]
        return chosen, SamplePlan("random", limit, seed, {}, is_full=False, total_available=total_available)

    if strategy != "stratified":
        raise ValueError(f"unknown sampling strategy: {strategy}")

    group_sizes = {g: len(v) for g, v in by_group.items()}
    alloc = _allocate_hamilton(group_sizes, limit)
    chosen: list[RubricCase] = []
    for g, budget in sorted(alloc.items()):
        chosen.extend(_balance_select(by_group[g], budget, rng))
    chosen.sort(key=lambda c: c.case_id)
    return chosen, SamplePlan("stratified", limit, seed, alloc, is_full=False, total_available=total_available)
