from ..errors import InvalidJudgeOutput
from ..models import DimensionScore

def parse_score(task_id: str, output: dict, source: str, lineage=None) -> DimensionScore:
    if not isinstance(output, dict) or "value" not in output:
        raise InvalidJudgeOutput("structured value is required")
    try: value = float(output["value"])
    except (TypeError, ValueError) as exc: raise InvalidJudgeOutput("value must be numeric") from exc
    try:
        return DimensionScore(task_id, value, source, output.get("raw", output), output.get("reason"), list(output.get("evidence_refs", [])), lineage or {})
    except ValueError as exc: raise InvalidJudgeOutput(str(exc)) from exc
