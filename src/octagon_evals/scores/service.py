from ..models import DimensionScore, DimensionTask, EvalPlan
from ..scorers.base import parse_score

class ScoreStore:
    """Append-only score store: a task can be resolved once, while proposals remain inspectable."""
    def __init__(self, db=None): self.proposals: dict[str, list[DimensionScore]] = {}; self.resolved: dict[str, DimensionScore] = {}; self.db = db
    def record(self, task: DimensionTask, output: dict, source: str, lineage: dict | None = None, resolve=True) -> DimensionScore:
        if task.id in self.resolved: return self.resolved[task.id]
        score = parse_score(task.id, output, source, lineage)
        self.proposals.setdefault(task.id, []).append(score)
        if resolve: self.resolved[task.id] = score
        if self.db: self.db.save_score(score, resolve)
        return score
    def resolve(self, task_id: str, policy="proposal") -> DimensionScore:
        score = self.resolved.get(task_id) or self.proposals[task_id][-1]
        score.resolved_policy = policy; self.resolved[task_id] = score; return score
