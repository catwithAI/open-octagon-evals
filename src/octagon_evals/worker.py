from .service import EvaluationService

class DeterministicWorker:
    def __init__(self, service: EvaluationService, plan, evidence_by_task: dict):
        self.service, self.plan, self.evidence_by_task = service, plan, evidence_by_task
    def run_once(self):
        processed=[]
        for task in list(self.service.tasks.tasks.values()):
            if task.method != "deterministic" or task.state != "queued": continue
            self.service.tasks.claim(task.id)
            try:
                self.service.score_deterministic(task, self.plan, self.evidence_by_task.get(task.id, {})); processed.append(task.id)
            except Exception:
                self.service.tasks.retry(task.id)
        return processed
