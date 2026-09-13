import yaml
from pathlib import Path
from ..models import EvalPlan, Dimension
from .validator import validate_plan
from .hash import plan_hash

def load_plan(source: str | Path | dict, capabilities: set[str] | None = None) -> EvalPlan:
    data = yaml.safe_load(Path(source).read_text()) if isinstance(source, (str, Path)) else source
    root = data.get("eval", data); p = root.get("plan", root)
    dims = tuple(Dimension(**d) for d in p.get("dimensions", []))
    plan = EvalPlan(root.get("schema_version", 1), p.get("version", 1), dims, root.get("scenario_id"), root.get("scenario_version"))
    validate_plan(plan, capabilities)
    return EvalPlan(plan.schema_version, plan.version, plan.dimensions, plan.scenario_id, plan.scenario_version, plan_hash(plan))
