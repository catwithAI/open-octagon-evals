from __future__ import annotations
import json
import subprocess
from functools import lru_cache

from fastapi import FastAPI, HTTPException

from ..errors import InvalidJudgeOutput
from ..scorers.base import parse_judge_content, parse_score
from .config import JudgeServiceConfig
from .models import JudgeRequest, JudgeResponse
from .pi_runner import PiRunner
from .workspace import cleanup_workspace, create_evidence_workspace

_JUDGE_SERVICE_VERSION = "0.1.0"

_DEFAULT_REQUIRED = ["value", "reason", "raw"]


def _validate_required(output: dict, output_schema: dict) -> None:
    """裁决必须包含 output_schema.required 声明的键（默认 value/reason/raw）。"""
    required = (output_schema or {}).get("required") or _DEFAULT_REQUIRED
    missing = [k for k in required if k not in output]
    if missing:
        raise InvalidJudgeOutput(
            f"judge output missing required key(s): {missing}"
        )


def _build_user_prompt(request: JudgeRequest) -> str:
    payload = {
        "instruction": (
            "The evidence files are in the current directory (evidence.json "
            "and the evidence/ folder). Read them if you need to, then reply "
            "with the JSON verdict."
        ),
        "question": request.dimension_question,
        "anchors": request.anchors,
        "output_schema": request.output_schema or {
            "type": "object",
            "required": ["value", "reason", "raw"],
            "value_range": [0, 1],
        },
        "evidence_location": "evidence.json (full) and evidence/ (per-key files)",
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


@lru_cache(maxsize=1)
def _get_pi_version(pi_bin: str) -> str:
    try:
        result = subprocess.run(
            [pi_bin, "--version"], capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def create_judge_app(
    config: JudgeServiceConfig | None = None, *, runner: PiRunner | None = None
) -> FastAPI:
    config = config or JudgeServiceConfig.from_env()
    app = FastAPI(title="octagon-judge-service", version=_JUDGE_SERVICE_VERSION)
    pi_runner = runner or PiRunner(config)
    judged: set[str] = set()

    @app.post("/judge", response_model=JudgeResponse)
    def judge(request: JudgeRequest):
        if request.task_id in judged:
            raise HTTPException(409, "task already judged")
        workspace = create_evidence_workspace(
            request.evidence, config.workspace_base, files=request.files
        )
        try:
            content = pi_runner.run(
                prompt=_build_user_prompt(request),
                workspace=workspace,
                system_prompt=request.system_prompt,
            )
            output = parse_judge_content(content)
            _validate_required(output, request.output_schema)
            lineage = dict(request.lineage)
            lineage.update(
                {
                    "provider": config.provider or "pi-default",
                    "model": config.model or "pi-default",
                    "prompt_version": config.prompt_version,
                    "judge_service_version": _JUDGE_SERVICE_VERSION,
                    "pi_version": _get_pi_version(config.pi_bin),
                }
            )
            value = None
            if "value" in output:
                score = parse_score(request.task_id, output, "agent_judge_agentic", lineage)
                value = score.value
                lineage = score.lineage
            judged.add(request.task_id)
            return JudgeResponse(
                task_id=request.task_id,
                result=output,
                value=value,
                reason=output.get("reason"),
                raw=output.get("raw"),
                source="agent_judge_agentic",
                lineage=lineage,
            )
        except InvalidJudgeOutput as exc:
            raise HTTPException(422, str(exc)) from exc
        finally:
            cleanup_workspace(workspace)

    @app.get("/health")
    def health():
        return {"status": "ok", "pi_version": _get_pi_version(config.pi_bin)}

    return app


judge_app = create_judge_app()
