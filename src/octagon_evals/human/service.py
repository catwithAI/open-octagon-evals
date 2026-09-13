from dataclasses import dataclass
import json
from ..errors import StaleSubmission
from ..scorers.base import parse_score

@dataclass
class HumanTask:
    id: str; run_id: str; dimension_id: str; evidence_refs: list[str]; reviewer_id: str | None = None
    state: str = "pending"; score: object | None = None

class HumanTaskStore:
    def __init__(self, db=None): self.tasks: dict[str, HumanTask] = {}; self.db = db
    def _get(self, task_id):
        task = self.tasks.get(task_id)
        if task is not None or self.db is None:
            return task
        try:
            row = self.db.get_human_task(task_id)
        except KeyError:
            return None
        score = None
        if row["score_json"]:
            try:
                payload = json.loads(row["score_json"])
                score = parse_score(task_id, payload, "human", {"reviewer_id": row["reviewer_id"]})
            except (TypeError, ValueError, json.JSONDecodeError):
                score = None
        task = HumanTask(task_id, row["run_id"], row["dimension_id"], json.loads(row["evidence_refs"] or "[]"), row["reviewer_id"], row["state"], score)
        self.tasks[task_id] = task
        return task
    def create(self, task_id, run_id, dimension_id, evidence_refs=()):
        task = self.tasks.setdefault(task_id, HumanTask(task_id, run_id, dimension_id, list(evidence_refs)))
        if self.db: self.db.save_human_task(task)
        return task
    def assign(self, task_id, reviewer_id):
        task=self._get(task_id)
        if task is None: raise KeyError(task_id)
        task.reviewer_id=reviewer_id; task.state="assigned"
        if self.db: self.db.save_human_task(task)
        return task
    def submit(self, task_id, reviewer_id, output):
        task=self._get(task_id)
        if task is None: raise KeyError(task_id)
        if task.state == "completed": return task.score
        if task.reviewer_id != reviewer_id: raise StaleSubmission("reviewer mismatch")
        task.score=parse_score(task.id, output, "human", {"reviewer_id": reviewer_id}); task.state="completed"
        if self.db: self.db.save_human_task(task)
        return task.score
    def expire(self, task_id):
        task=self._get(task_id)
        if task is None: raise KeyError(task_id)
        if task.state != "completed":
            task.state="pending"; task.reviewer_id=None
            if self.db: self.db.save_human_task(task)
