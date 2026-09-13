from ..models import Dimension, DimensionScore

def aggregate(dimensions: list[Dimension], scores: dict[str, DimensionScore], *, plan_hash=None) -> dict:
    scored = [d for d in dimensions if d.role == "scored"]
    if any(d.id not in scores for d in scored): return {"status": "pending", "total_score": None, "plan_hash": plan_hash}
    denominator = sum(d.weight for d in scored)
    total = sum(scores[d.id].value * d.weight for d in scored) / denominator
    return {"status": "final", "total_score": total, "plan_hash": plan_hash, "score_ids": sorted(s.task_id for s in scores.values())}
