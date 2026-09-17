import math
from ..errors import PlanError
from ..models import EvalPlan

def validate_plan(plan: EvalPlan, capabilities: set[str] | None = None) -> EvalPlan:
    if plan.schema_version != 1 or not plan.dimensions:
        raise PlanError("unsupported schema or empty plan")
    ids = set()
    scored = 0.0
    for d in plan.dimensions:
        if not d.id or d.id in ids: raise PlanError(f"duplicate/empty dimension: {d.id}")
        ids.add(d.id)
        if capabilities is not None and d.id not in capabilities: raise PlanError(f"unknown dimension: {d.id}")
        if d.role not in ("scored", "diagnostic") or d.method not in ("deterministic", "agent_judge", "agent_judge_agentic", "human_required"):
            raise PlanError(f"invalid role or method for {d.id}")
        if not isinstance(d.weight, (int, float)) or isinstance(d.weight, bool) or not math.isfinite(d.weight) or d.weight < 0:
            raise PlanError(f"invalid weight for {d.id}")
        if d.role == "scored": scored += d.weight
    if scored <= 0: raise PlanError("scored weights must sum to > 0")
    return plan
