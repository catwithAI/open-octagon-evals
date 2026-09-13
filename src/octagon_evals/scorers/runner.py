from .registry import ScorerRegistry
from .base import parse_score

class ScorerRunner:
    def __init__(self, registry: ScorerRegistry): self.registry = registry; self.calls: dict[str, int] = {}
    def run(self, task, evidence, *, lineage=None):
        spec = self.registry.get(task.dimension_id)
        if spec.method != task.method: raise ValueError("task method does not match scorer")
        # The runner owns invocation count: a retry/re-delivery cannot sample twice.
        # A handler that raised never sampled, so it stays callable for the retry path.
        if task.id in self.calls: raise RuntimeError(f"scorer already called for {task.id}")
        output = spec.handler(evidence)
        self.calls[task.id] = 1
        return parse_score(task.id, output, spec.method, {**(lineage or {}), "scorer_version": spec.version, "source_hash": spec.source_hash})
