import hashlib, json
from dataclasses import asdict
from ..models import EvalPlan

def plan_hash(plan: EvalPlan) -> str:
    payload = asdict(plan); payload.pop("plan_hash", None)
    return "sha256:" + hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
