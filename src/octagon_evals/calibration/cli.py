"""一键校准 LLM-as-judge：python -m octagon_evals.calibration。

跑 RubricBench 官方协议（人工 gold + 官方 rubric + 论文 Appendix F prompt），
默认 **inline**（OpenAI-compatible 单次调用，即 `agent_judge` 的 LLM-as-judge
语义；RubricBench 无证据检索，不走 agentic）。默认分层抽样，裁决按
(case_id, prompt_version, system_prompt_hash) 幂等落 JSONL 可续跑，产出
markdown 可信度报告。
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as _dt
import hashlib
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..judge_service.config import JudgeServiceConfig
from ..scorers.agent_judge import AgentJudgeConfig
from .judge import JudgeIdentity, JudgeTransport
from .metrics import aggregate
from .report import render_report
from .rubricbench import (
    GROUP_LABELS,
    PROMPT_VERSION,
    RUBRICBENCH_SYSTEM_PROMPT,
    build_user_prompt,
    load_cases,
    normalize_group_selector,
    parse_verdict,
)
from .sampling import sample_cases


def _parse_groups(value: str | None) -> set[str] | None:
    if not value:
        return None
    groups = set()
    for part in value.split(","):
        group = normalize_group_selector(part)
        if group:
            groups.add(group)
    return groups or None


def load_verdicts(path: str | Path) -> dict[tuple[str, str, str], dict]:
    """读 verdicts JSONL；按 (case_id, prompt_version, system_prompt_hash)
    去重，后写覆盖先写（与 rubricbench 重复行语义一致）。"""
    result: dict[tuple[str, str, str], dict] = {}
    path = Path(path)
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        key = (rec["case_id"], rec["prompt_version"], rec["system_prompt_hash"])
        result[key] = rec
    return result


def append_verdict(path: str | Path, rec: dict) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="python -m octagon_evals.calibration",
        description="RubricBench pairwise judge 校准（官方协议，默认抽样）",
    )
    ap.add_argument("--data", required=True, help="rubricbench_data.json 路径（仓库之外）")
    ap.add_argument("--backend", choices=("inline", "agentic"), default="inline",
                    help="默认 inline = LLM-as-judge（OpenAI-compatible 单次调用）；agentic 保留作对照")
    ap.add_argument("--strategy", choices=("stratified", "random", "full"), default="stratified")
    ap.add_argument("--domains", default=None, help="分组过滤，逗号分隔，如 code,chat（IF/STEM/CODE/SAFE/CHAT）")
    ap.add_argument("--limit", type=int, default=100, help="抽样预算（full 时忽略；默认 100）")
    ap.add_argument("--seed", type=int, default=1, help="抽样固定种子")
    ap.add_argument("--provider", default=None, help="覆盖 agentic provider（默认读环境）")
    ap.add_argument("--model", default=None, help="覆盖 judge model（默认读环境）")
    ap.add_argument("--verdicts", default=None, help="裁决 JSONL 路径（幂等落库，可续跑）")
    ap.add_argument("--concurrency", type=int, default=4, help="并发 judge 调用数（默认 4，1 为串行）")
    ap.add_argument("--force", action="store_true", help="重判已存在 case")
    ap.add_argument("--out", default="calibration_report.md", help="报告输出路径")
    return ap


def main(argv: list[str] | None = None, *, transport: JudgeTransport | None = None, log=print) -> int:
    args = build_parser().parse_args(argv)

    cases = load_cases(args.data)
    selected, plan = sample_cases(
        cases,
        strategy=args.strategy,
        limit=args.limit,
        seed=args.seed,
        groups=_parse_groups(args.domains),
    )
    if not selected:
        log("no cases selected (检查 --domains/--limit/数据路径)")
        return 1

    data_hash = hashlib.sha256(Path(args.data).read_bytes()).hexdigest()[:16]
    system_prompt_hash = hashlib.sha256(RUBRICBENCH_SYSTEM_PROMPT.encode()).hexdigest()

    existing = load_verdicts(args.verdicts) if args.verdicts else {}
    agentic_config = JudgeServiceConfig.from_env()
    if args.provider:
        agentic_config = dataclasses.replace(agentic_config, provider=args.provider)
    if args.model:
        agentic_config = dataclasses.replace(agentic_config, model=args.model)
    inline_config = AgentJudgeConfig.from_env()
    if args.model:
        inline_config = dataclasses.replace(inline_config, model=args.model)
    transport = transport or JudgeTransport(agentic_config=agentic_config, inline_config=inline_config)

    append_lock = threading.Lock()

    def judge_one(case) -> tuple[dict, bool, JudgeIdentity | None]:
        """判一个 case：命中已有裁决则复用；否则调用 judge 并追加落库（并发安全）。"""
        key = (case.case_id, PROMPT_VERSION, system_prompt_hash)
        if not args.force and key in existing:
            return existing[key], False, None
        user_prompt = build_user_prompt(case)
        raw, ident = transport.judge(
            backend=args.backend, system_prompt=RUBRICBENCH_SYSTEM_PROMPT, user_prompt=user_prompt
        )
        verdict = parse_verdict(raw)
        rec = {
            "case_id": case.case_id,
            "group": GROUP_LABELS.get(case.group, case.group) if case.group else None,
            "prompt_version": PROMPT_VERSION,
            "system_prompt_hash": system_prompt_hash,
            "user_prompt": user_prompt,
            "raw_output": raw,
            "verdict": verdict,
            "gold": case.label,
            "backend": ident.backend,
            "model": ident.model,
            "provider": ident.provider,
            "correct": verdict == case.label,
        }
        if args.verdicts:
            with append_lock:
                append_verdict(args.verdicts, rec)
        return rec, True, ident

    concurrency = max(1, args.concurrency or 1)
    if concurrency == 1:
        results = [judge_one(c) for c in selected]
    else:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            results = list(pool.map(judge_one, selected))

    records = [r for r, _, _ in results]
    fresh = sum(1 for _, is_new, _ in results if is_new)
    identity = next((ident for _, _, ident in results if ident is not None), None)

    if identity is None and records:
        first = records[0]
        identity = JudgeIdentity(first["backend"], first["model"], first.get("provider"), first["prompt_version"])
    if identity is None:
        identity = JudgeIdentity(args.backend, "unknown", None, PROMPT_VERSION)

    rows = aggregate(records)
    wrong = [r for r in records if not r["correct"]]
    reused = len(records) - fresh
    meta = {
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "backend": identity.backend,
        "model": identity.model,
        "provider": identity.provider,
        "prompt_version": PROMPT_VERSION,
        "data_path": str(args.data),
        "data_hash": data_hash,
        "strategy": plan.strategy,
        "limit": plan.limit,
        "seed": plan.seed,
        "allocation": {GROUP_LABELS.get(g, g): n for g, n in plan.allocation.items()},
        "is_full": plan.is_full,
        "total_available": plan.total_available,
        "verdicts_path": args.verdicts,
        "concurrency": concurrency,
    }
    report = render_report(meta=meta, rows=rows, wrong_cases=wrong)
    Path(args.out).write_text(report, encoding="utf-8")

    overall = rows[0]
    log(
        f"已覆盖 {len(records)} case（新判 {fresh}，复用 {reused}，invalid {overall.invalid}，"
        f"并发 {concurrency}）；Overall ACC = {overall.acc:.4f} "
        f"[95% CI {overall.ci_lo:.2f}, {overall.ci_hi:.2f}]"
    )
    log(f"报告已写入 {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
