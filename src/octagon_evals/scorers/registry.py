from dataclasses import dataclass
from typing import Callable, Any
from ..errors import PlanError

@dataclass(frozen=True)
class ScorerSpec:
    dimension_id: str
    method: str
    version: str
    source_hash: str
    handler: Callable[..., dict[str, Any]]

class ScorerRegistry:
    def __init__(self): self._items: dict[str, ScorerSpec] = {}
    def register(self, spec: ScorerSpec):
        if spec.dimension_id in self._items: raise PlanError(f"scorer already registered: {spec.dimension_id}")
        self._items[spec.dimension_id] = spec
    def get(self, dimension_id: str) -> ScorerSpec:
        try: return self._items[dimension_id]
        except KeyError as exc: raise PlanError(f"unknown dimension: {dimension_id}") from exc
    def capabilities(self) -> set[str]: return set(self._items)
