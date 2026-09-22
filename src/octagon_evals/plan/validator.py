import math
from ..errors import PlanError
from ..models import COMPARISON_METHODS, EvalPlan

_METHODS = ("deterministic", "agent_judge", "agent_judge_agentic", "jev_judge",
            "pairwise_judge", "pairwise_judge_agentic",
            "listwise_judge", "listwise_judge_agentic", "human_required")

_VALID_JEV_TYPES = ("choice", "score", "noul")

def validate_plan(plan: EvalPlan, capabilities: set[str] | None = None) -> EvalPlan:
    if plan.schema_version != 1 or not plan.dimensions:
        raise PlanError("unsupported schema or empty plan")
    ids = set()
    scored = 0.0
    for d in plan.dimensions:
        if not d.id or d.id in ids: raise PlanError(f"duplicate/empty dimension: {d.id}")
        ids.add(d.id)
        if capabilities is not None and d.id not in capabilities: raise PlanError(f"unknown dimension: {d.id}")
        if d.role not in ("scored", "diagnostic") or d.method not in _METHODS:
            raise PlanError(f"invalid role or method for {d.id}")
        if not isinstance(d.weight, (int, float)) or isinstance(d.weight, bool) or not math.isfinite(d.weight) or d.weight < 0:
            raise PlanError(f"invalid weight for {d.id}")
        if d.method in COMPARISON_METHODS:
            _validate_comparison(d)
        if d.method == "jev_judge":
            _validate_jev(d)
        if d.role == "scored": scored += d.weight
    if scored <= 0: raise PlanError("scored weights must sum to > 0")
    return plan


def _validate_jev(d):
    """JEV questions 结构校验：非空 dict、每问有合法 type 与 instructions、
    choice/score 有 criteria（choice 可选 expected）。"""
    questions = d.jev_questions
    if not isinstance(questions, dict) or not questions:
        raise PlanError(f"jev_judge dimension {d.id} requires declared jev_questions")
    for name, q in questions.items():
        if not isinstance(q, dict):
            raise PlanError(f"jev question {d.id}.{name} must be an object")
        qtype = q.get("type")
        if qtype not in _VALID_JEV_TYPES:
            raise PlanError(f"jev question {d.id}.{name}: invalid type {qtype!r}")
        if not q.get("instructions"):
            raise PlanError(f"jev question {d.id}.{name}: instructions required")
        if qtype in ("choice", "score") and not isinstance(q.get("criteria"), dict):
            raise PlanError(f"jev question {d.id}.{name}: criteria required for {qtype}")


def _validate_comparison(d):
    """比较维度的配置校验。max_candidates 是运行期对候选数的上限，
    run 数量未知，plan 校验不检查它，由比较编排在提交时执行。
    """
    config = d.comparison
    if config is None:
        return
    pairwise = d.method.startswith("pairwise")
    if pairwise:
        allowed = ("win_count", "bradley_terry")
    else:
        # listwise：默认 conversion=win_count 是"未指定"的占位，
        # 运行期统一替换为 rank_interpolation；显式传其他值才拒绝。
        allowed = ("rank_interpolation", "win_count")
    if config.conversion not in allowed:
        raise PlanError(f"invalid comparison conversion for {d.id}: {config.conversion}")
