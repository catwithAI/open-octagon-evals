from __future__ import annotations
import json
import os
import shutil
import tempfile
from typing import Any


def create_evidence_workspace(evidence: dict[str, Any], base_dir: str | None = None) -> str:
    """Write the evidence dict into a fresh temp dir the judge agent can explore.

    The full dict is dumped to ``evidence.json`` and each top-level key is also
    written as its own file under ``evidence/`` so pi can ``ls``, read, or grep
    with its tools rather than being handed everything in the prompt.
    """
    workspace = tempfile.mkdtemp(prefix="octagon-judge-", dir=base_dir)
    with open(os.path.join(workspace, "evidence.json"), "w") as f:
        json.dump(evidence, f, indent=2, ensure_ascii=False)
    evidence_dir = os.path.join(workspace, "evidence")
    os.makedirs(evidence_dir, exist_ok=True)
    used_names: set[str] = set()
    for key, value in evidence.items():
        base_name = _safe_filename(key)
        filename = base_name
        suffix = 2
        while filename in used_names:
            filename = f"{base_name}_{suffix}"
            suffix += 1
        used_names.add(filename)
        with open(os.path.join(evidence_dir, filename), "w") as f:
            if isinstance(value, (dict, list)):
                json.dump(value, f, indent=2, ensure_ascii=False)
            else:
                f.write(str(value))
    return workspace


def cleanup_workspace(path: str) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _safe_filename(key: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in key)
    return safe[:100] or "item"
