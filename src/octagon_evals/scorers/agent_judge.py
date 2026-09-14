from __future__ import annotations
import json, os, re
from dataclasses import dataclass
from urllib.request import Request, urlopen
from ..errors import InvalidJudgeOutput
from .base import parse_score

_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _parse_judge_content(content: str) -> dict:
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

@dataclass(frozen=True)
class AgentJudgeConfig:
    endpoint: str = "https://api.openai.com/v1/chat/completions"
    model: str = "stealth/ox-alpha"
    api_key: str | None = None
    prompt_version: str = "1"
    @classmethod
    def from_env(cls):
        return cls(os.getenv("OCTAGON_JUDGE_ENDPOINT", cls.endpoint), os.getenv("OCTAGON_JUDGE_MODEL", "stealth/ox-alpha"), os.getenv("OCTAGON_JUDGE_API_KEY"), os.getenv("OCTAGON_JUDGE_PROMPT_VERSION", "1"))

class AgentJudge:
    def __init__(self, config: AgentJudgeConfig, opener=urlopen):
        self.config, self.opener = config, opener
        # A judge may score many tasks, but each logical task/dimension is
        # sampled at most once.  The old single integer blocked the second
        # dimension in an otherwise valid run.
        self.calls = 0
        self._called_tasks: set[str] = set()
    def score(self, task_id: str, evidence: dict, dimension_question: str,
              *, anchors=None, output_schema=None):
        if task_id in self._called_tasks: raise RuntimeError("agent judge is single-call per dimension")
        judge_input = {
            "question": dimension_question,
            "anchors": anchors or [],
            "output_schema": output_schema or {
                "type": "object",
                "required": ["value", "reason", "raw"],
                "value_range": [0, 1],
            },
            "evidence": evidence,
        }
        system_prompt = (
            "You are a strict evaluation judge. Return JSON only with keys "
            "value, reason, and raw. Use only the supplied evidence. Apply "
            "the anchors literally: a requirement passes only when the "
            "candidate provides the concrete evidence described; saying that "
            "something should be clarified later does not count as passing. "
            "Do not infer missing agent, model, judge, version, or alignment "
            "details. value must be a finite number in [0,1]. Put one "
            "pass/fail decision per anchor in raw when anchors are provided."
        )
        payload={"model":self.config.model,"temperature":0,"messages":[{"role":"system","content":system_prompt},{"role":"user","content":json.dumps(judge_input, ensure_ascii=False)}]}
        headers={"Content-Type":"application/json"}
        if self.config.api_key: headers["Authorization"]="Bearer "+self.config.api_key
        req=Request(self.config.endpoint,data=json.dumps(payload).encode(),headers=headers,method="POST")
        with self.opener(req) as response: body=json.loads(response.read())
        content=body["choices"][0]["message"]["content"]
        output=_parse_judge_content(content) if isinstance(content,str) else content
        score = parse_score(task_id, output, "agent_judge", {"model":self.config.model,"prompt_version":self.config.prompt_version})
        self._called_tasks.add(task_id)
        self.calls += 1
        return score
