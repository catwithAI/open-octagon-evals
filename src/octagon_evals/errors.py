class EvalError(Exception):
    """Base domain error."""

class InvalidInputError(EvalError): pass
class PlanError(EvalError): pass
class InvalidJudgeOutput(EvalError): pass
class InvalidStateTransition(EvalError): pass
class StaleSubmission(EvalError): pass
