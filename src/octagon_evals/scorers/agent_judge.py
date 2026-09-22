from __future__ import annotations
import json, os
from dataclasses import dataclass
from urllib.request import Request, urlopen
from .base import parse_judge_content, parse_score
from .comparison import validate_ranking, validate_winner

@dataclass(frozen=True)
class AgentJudgeConfig:
    endpoint: str = "https://api.openai.com/v1/chat/completions"
    model: str = "stealth/ox-alpha"
    api_key: str | None = None
    prompt_version: str = "1"
    @classmethod
    def from_env(cls):
        return cls(os.getenv("OCTAGON_JUDGE_ENDPOINT", cls.endpoint), os.getenv("OCTAGON_JUDGE_MODEL", "stealth/ox-alpha"), os.getenv("OCTAGON_JUDGE_API_KEY"), os.getenv("OCTAGON_JUDGE_PROMPT_VERSION", "1"))

_POINTWISE_SYSTEM = (
    "You are a strict evaluation judge. Return JSON only with keys "
    "value, reason, and raw. Use only the supplied evidence. Apply "
    "the anchors literally: a requirement passes only when the "
    "candidate provides the concrete evidence described; saying that "
    "something should be clarified later does not count as passing. "
    "Do not infer missing agent, model, judge, version, or alignment "
    "details. value must be a finite number in [0,1]. Put one "
    "pass/fail decision per anchor in raw when anchors are provided."
)

_COMPARE_SYSTEM = (
    "You are a strict pairwise evaluation judge. Compare the two candidates "
    "on the given question using only the supplied evidence. Their order and "
    "labels are arbitrary — position and label carry no signal, so ignore "
    "them and judge purely by substance. State a brief point-by-point "
    "comparison, then return JSON only with keys winner, reason, raw. "
    "winner is exactly one of the two candidate ids, or the string 'tie'. "
    "Do not infer missing agent, model, judge, or alignment details."
)

_RANK_SYSTEM = (
    "You are a strict listwise evaluation judge. Rank all candidates on the "
    "given question using only the supplied evidence. Examine every candidate "
    "before deciding; position in the list carries no signal. Return JSON only "
    "with keys ranking, reason, raw. ranking is an array of every candidate id, "
    "best first, exactly once each. Do not infer missing agent, model, judge, "
    "or alignment details."
)


class AgentJudge:
    """LLM-as-judge 后端：OpenAI-compatible 单次调用。

    实现 JudgeBackend 协议：score / compare / rank 三个入口，各带方法级
    system prompt。一个 judge 可评分多个任务，但每个逻辑 task_id 只采样一次。
    """
    def __init__(self, config: AgentJudgeConfig, opener=urlopen):
        self.config, self.opener = config, opener
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
        output = self._post(judge_input, _POINTWISE_SYSTEM)
        score = parse_score(task_id, output, "agent_judge", {"model": self.config.model, "prompt_version": self.config.prompt_version})
        self._called_tasks.add(task_id)
        self.calls += 1
        return score

    def compare(self, task_id: str, candidates: list[dict], dimension_question: str,
                *, anchors=None, allow_ties: bool = True, output_schema=None) -> dict:
        if task_id in self._called_tasks: raise RuntimeError("agent judge is single-call per pair")
        if len(candidates) != 2:
            raise ValueError("pairwise judge requires exactly two candidates")
        judge_input = {
            "question": dimension_question,
            "anchors": anchors or [],
            "allow_ties": allow_ties,
            "candidates": candidates,
        }
        output = self._post(judge_input, _COMPARE_SYSTEM)
        run_a, run_b = candidates[0]["id"], candidates[1]["id"]
        # 裁决以 run id 表示（或 'tie'），不做呈现顺序归一化；语义校验在主体 scorer。
        validate_winner(output, run_a, run_b, allow_ties=allow_ties)
        self._called_tasks.add(task_id)
        self.calls += 1
        return {"winner": output["winner"], "reason": output.get("reason"), "raw": output.get("raw")}

    def rank(self, task_id: str, candidates: list[dict], dimension_question: str,
             *, anchors=None, output_schema=None) -> dict:
        if task_id in self._called_tasks: raise RuntimeError("agent judge is single-call per rank")
        if len(candidates) < 2:
            raise ValueError("listwise judge requires at least two candidates")
        judge_input = {
            "question": dimension_question,
            "anchors": anchors or [],
            "candidates": candidates,
        }
        output = self._post(judge_input, _RANK_SYSTEM)
        run_ids = [c["id"] for c in candidates]
        ranking = validate_ranking(output, run_ids)
        self._called_tasks.add(task_id)
        self.calls += 1
        return {"ranking": ranking, "reason": output.get("reason"), "raw": output.get("raw")}

    def _post(self, judge_input: dict, system_prompt: str) -> dict:
        payload = {"model": self.config.model, "temperature": 0, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": json.dumps(judge_input, ensure_ascii=False)}]}
        headers = {"Content-Type": "application/json"}
        if self.config.api_key: headers["Authorization"] = "Bearer " + self.config.api_key
        req = Request(self.config.endpoint, data=json.dumps(payload).encode(), headers=headers, method="POST")
        with self.opener(req) as response:
            body = json.loads(response.read())
        content = body["choices"][0]["message"]["content"]
        return parse_judge_content(content) if isinstance(content, str) else content
