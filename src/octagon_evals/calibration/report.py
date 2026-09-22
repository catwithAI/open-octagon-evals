"""校准报告渲染：markdown，含抽样信息、置信区间、官方基线参照、错误案例抽样。

官方基线（rubricbench README 的 gemini3-flash rubric 系统，全量 ACC）只作
参照，不参与我们的统计：抽样 ACC 与全量基线口径不同，报告里明确标注。
"""
from __future__ import annotations

import datetime as _dt
from typing import Any

# rubricbench README 官方样例基线（全量 ACC），仅供对照 judge 大致落位。
OFFICIAL_BASELINES = [
    ("openrubric_gemini3-flash", 0.7419, 0.6520, 0.5904, 0.2500, 0.5450, 0.5798),
    ("checkeval_rubric_gemini3-flash", 0.6935, 0.6320, 0.6310, 0.3750, 0.4953, 0.5702),
    ("auto_rubric_gemini3-flash", 0.6935, 0.6320, 0.6310, 0.2875, 0.5024, 0.5667),
    ("rocket_rubric_gemini3-flash", 0.5565, 0.5960, 0.5572, 0.2875, 0.6066, 0.5650),
]


def _f(value: float, digits: int = 4) -> str:
    return f"{value:.{digits}f}"


def _ci(row) -> str:
    return f"[{_f(row.ci_lo, 2)}, {_f(row.ci_hi, 2)}]"


def _results_table(rows) -> str:
    header = "| 分组 | judged | ACC | 95% CI | ValidACC | invalid |"
    sep = "|---|---|---|---|---|---|"
    lines = [header, sep]
    for row in rows:
        lines.append(
            f"| {row.group} | {row.total} | {_f(row.acc)} | {_ci(row)} | "
            f"{_f(row.valid_acc)} | {row.invalid} |"
        )
    return "\n".join(lines)


def _baseline_table(rows) -> str:
    header = "| 系统（gemini3-flash, 全量） | IF | STEM | CODE | SAFE | CHAT | Overall |"
    sep = "|---|---|---|---|---|---|---|"
    lines = [header, sep]
    for name, *accs in rows:
        lines.append(f"| {name} | " + " | ".join(_f(a) for a in accs) + " |")
    return "\n".join(lines)


def _sampling_block(meta: dict[str, Any]) -> str:
    strategy = meta["strategy"]
    if strategy == "full":
        return f"- 抽样策略：**全量**（{meta['total_available']} case，limit 超出可用量自动转全量）"
    lines = [f"- 抽样策略：**{strategy}**，limit={meta['limit']}，seed={meta['seed']}"]
    if strategy == "stratified":
        alloc = meta.get("allocation") or {}
        alloc_str = "、".join(f"{g}={n}" for g, n in sorted(alloc.items())) or "-"
        lines.append(f"- 分组分配：{alloc_str}（可用 {meta['total_available']} case）")
    else:
        lines.append(f"- 随机抽取（可用 {meta['total_available']} case）")
    return "\n".join(lines)


def _wrong_cases_block(wrong_cases: list[dict[str, Any]], limit: int = 5) -> str:
    if not wrong_cases:
        return "_无错误案例。_"
    lines = ["| case_id | group | gold | pred | 理由截断 |", "|---|---|---|---|---|"]
    for rec in wrong_cases[:limit]:
        snippet = (rec.get("raw_output") or "").replace("\n", " ").strip()[:120]
        lines.append(
            f"| {rec['case_id']} | {rec.get('group') or '-'} | {rec['gold']} | "
            f"{rec['verdict'] if rec.get('verdict') is not None else 'invalid'} | {snippet} |"
        )
    if len(wrong_cases) > limit:
        lines.append(f"_…另有 {len(wrong_cases) - limit} 个错误案例，见 verdicts 文件。_")
    return "\n".join(lines)


def render_report(*, meta: dict[str, Any], rows, wrong_cases, include_baselines: bool = True) -> str:
    """meta：backend/model/provider/prompt_version/data_path/data_hash/
    strategy/limit/seed/allocation/is_full/total_available/verdicts_path/
    generated_at。rows：``metrics.aggregate`` 输出。wrong_cases：错误案例记录。"""
    overall = rows[0] if rows else None
    method = "LLM-as-judge（inline，单次调用）" if meta["backend"] == "inline" else "Agent-as-judge（agentic，pi）"
    lines = [
        "# Judge 校准报告（RubricBench pairwise）",
        "",
        f"- 生成时间：{meta.get('generated_at', _dt.datetime.now().isoformat(timespec='seconds'))}",
        f"- 校准对象：**{method}**",
        f"- backend：{meta['backend']}",
        f"- model：{meta['model']}",
    ]
    if meta.get("provider"):
        lines.append(f"- provider：{meta['provider']}")
    lines += [
        f"- prompt_version：{meta['prompt_version']}（论文 arXiv:2603.01562 Appendix F + 官方原子 rubric）",
        f"- 数据：`{meta['data_path']}`（hash `{meta['data_hash']}`）",
        f"- verdicts：`{meta.get('verdicts_path') or '-'}`",
        "",
        _sampling_block(meta),
        "",
    ]
    if overall is not None:
        lines.append(
            f"## 总体\n\n- ACC = **{_f(overall.acc)}**（{overall.correct}/{overall.total}，invalid 按错计）"
            f"（95% CI {_ci(overall)}）\n"
            f"- ValidACC = {_f(overall.valid_acc)}，invalid = {overall.invalid}"
        )
    lines += ["", "## 分组", "", _results_table(rows), ""]
    if include_baselines:
        lines += [
            "## 与官方基线对比（参照）",
            "",
            "官方基线是 gemini3-flash rubric 系统的**全量** ACC；我们可能是抽样，口径不完全"
            "可比，仅作落位参照。",
            "",
            _baseline_table(OFFICIAL_BASELINES),
            "",
        ]
    lines += ["## 错误案例抽样", "", _wrong_cases_block(wrong_cases), ""]
    return "\n".join(lines)
