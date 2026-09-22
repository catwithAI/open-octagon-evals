from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Literal
import math

Role = Literal["scored", "diagnostic"]
Method = Literal["deterministic", "agent_judge", "agent_judge_agentic",
                 "pairwise_judge", "pairwise_judge_agentic",
                 "listwise_judge", "listwise_judge_agentic", "human_required"]
ComparisonStrategy = Literal["round_robin", "sampled"]
ComparisonConversion = Literal["win_count", "bradley_terry", "rank_interpolation"]
COMPARISON_METHODS = (
    "pairwise_judge", "pairwise_judge_agentic",
    "listwise_judge", "listwise_judge_agentic",
)

def _value(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("value must be a finite number in [0, 1]")
    return float(value)

@dataclass(frozen=True)
class EvaluationInput:
    experiment_id: str
    run_id: str
    scenario: dict[str, Any]
    task: dict[str, Any]
    artifact: dict[str, Any]
    history: dict[str, Any]
    upstream_completed: bool
    # Optional producer metadata.  Keeping it on the immutable input makes a
    # score attributable to the agent/model/skill variant that produced it,
    # while the field remains backwards compatible with the original MVP
    # positional constructor.
    producer: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        required = ("experiment_id", "run_id", "scenario", "task", "artifact", "history")
        if any(not getattr(self, k) for k in required):
            raise ValueError("all EvaluationInput envelope fields are required")
        if not isinstance(self.experiment_id, str) or not self.experiment_id.strip():
            raise ValueError("experiment_id is required")
        if not isinstance(self.run_id, str) or not self.run_id.strip():
            raise ValueError("run_id is required")
        if not all(isinstance(getattr(self, k), dict) for k in ("scenario", "task", "artifact", "history", "producer")):
            raise ValueError("scenario, task, artifact, history and producer must be objects")
        if not self.artifact.get("snapshot_ref") or not self.artifact.get("content_hash"):
            raise ValueError("artifact snapshot_ref and content_hash are required")
        if not isinstance(self.artifact["snapshot_ref"], str) or not isinstance(self.artifact["content_hash"], str):
            raise ValueError("artifact snapshot_ref and content_hash must be strings")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvaluationInput":
        if not isinstance(data, dict):
            raise ValueError("invalid evaluation input: expected an object")
        try:
            run_status = data.get("run_status") or {}
            return cls(data["experiment_id"], data["run_id"], data["scenario"], data["task"], data["artifact"], data["history"], bool(run_status["upstream_completed"]), dict(data.get("producer") or {}))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid evaluation input: {exc}") from exc

@dataclass(frozen=True)
class ComparisonConfig:
    """配置一个比较维度（pairwise_judge* / listwise_judge*）的采样与转换。

    随 Dimension 一起被 plan_hash 序列化：比较模式随 plan 版本冻结，
    同一维度不会一会儿 pointwise 一会儿 comparison。
    """
    strategy: ComparisonStrategy = "round_robin"
    max_pairs: int = 0
    allow_ties: bool = True
    conversion: ComparisonConversion = "win_count"
    conversion_version: str = "1"
    max_candidates: int = 16

    def __post_init__(self):
        if self.strategy not in ("round_robin", "sampled"):
            raise ValueError("invalid comparison strategy")
        if self.conversion not in ("win_count", "bradley_terry", "rank_interpolation"):
            raise ValueError("invalid comparison conversion")
        if not isinstance(self.max_pairs, int) or self.max_pairs < 0:
            raise ValueError("max_pairs must be a non-negative integer")
        if self.max_candidates is not None and (not isinstance(self.max_candidates, int) or self.max_candidates < 2):
            raise ValueError("max_candidates must be an integer >= 2 or None")


@dataclass(frozen=True)
class Dimension:
    id: str
    version: int = 1
    role: Role = "scored"
    weight: float = 1.0
    method: Method = "deterministic"
    evidence: tuple[str, ...] = ()
    scorer_version: str = "1"
    question: str = ""
    anchors: Any = ()
    output_schema: dict[str, Any] = field(default_factory=dict)
    comparison: ComparisonConfig | None = None

    def __post_init__(self):
        # 从 dict 反序列化（API 请求、持久化 plan）时把 comparison 块转成配置对象。
        if isinstance(self.comparison, dict):
            object.__setattr__(self, "comparison", ComparisonConfig(**self.comparison))

@dataclass(frozen=True)
class EvalPlan:
    schema_version: int
    version: int
    dimensions: tuple[Dimension, ...]
    scenario_id: str | None = None
    scenario_version: int | str | None = None
    plan_hash: str | None = None

@dataclass
class DimensionTask:
    id: str
    experiment_id: str
    run_id: str
    plan_hash: str
    dimension_id: str
    method: Method
    state: str = "queued"
    attempts: int = 0
    lease_until: float | None = None


@dataclass
class ComparisonTask:
    """Experiment 级比较任务：一个实验 × 一个比较维度。

    不直接产出 DimensionScore；其相对裁决经确定性转换回写每-run 标量。
    """
    id: str
    experiment_id: str
    plan_hash: str
    dimension_id: str
    method: Method
    state: str = "queued"
    attempts: int = 0
    lease_until: float | None = None

@dataclass
class DimensionScore:
    task_id: str
    value: float
    source: str
    raw: Any = None
    reason: str | None = None
    evidence_refs: list[str] = field(default_factory=list)
    lineage: dict[str, Any] = field(default_factory=dict)
    reviews: list[dict[str, Any]] = field(default_factory=list)
    resolved_policy: str = "proposal"

    def __post_init__(self): self.value = _value(self.value)
