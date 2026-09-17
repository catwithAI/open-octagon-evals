import json
import re
from ..errors import InvalidJudgeOutput
from ..models import DimensionScore

_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def parse_judge_content(content: str) -> dict:
    """Decode the judge's message content into the structured verdict.

    Chat models routinely wrap JSON in a markdown fence or add a sentence
    before it, even when told to return JSON only.  A bare ``json.loads`` turns
    that into ``Expecting value: line 1 column 1`` — which surfaces as a 422 on
    the scoring endpoint and looks like a broken request rather than a judge
    that answered slightly off-format.  Peel the common wrappers first; only
    genuinely unparseable output is an invalid verdict.

    This never guesses a score: if no JSON object can be decoded, it raises and
    the dimension stays unresolved (per the MVP rule that invalid judge output
    must not be coerced to zero).
    """
    text = content.strip()
    candidates = [text]
    fenced = _FENCE.search(text)
    if fenced:
        candidates.append(fenced.group(1))
    # Last resort: the outermost {...} span, for prose-then-JSON replies.
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])
    for candidate in candidates:
        try:
            decoded = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(decoded, dict):
            return decoded
    raise InvalidJudgeOutput(
        f"judge did not return a JSON object (got {content[:200]!r})"
    )


def parse_score(task_id: str, output: dict, source: str, lineage=None) -> DimensionScore:
    if not isinstance(output, dict) or "value" not in output:
        raise InvalidJudgeOutput("structured value is required")
    try: value = float(output["value"])
    except (TypeError, ValueError) as exc: raise InvalidJudgeOutput("value must be numeric") from exc
    try:
        return DimensionScore(task_id, value, source, output.get("raw", output), output.get("reason"), list(output.get("evidence_refs", [])), lineage or {})
    except ValueError as exc: raise InvalidJudgeOutput(str(exc)) from exc
