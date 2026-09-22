"""RubricBench 校准：数据、官方 prompt、裁决解析、抽样、指标。

metrics 口径与 rubricbench ``eval_submission.py`` 一致：把其参考实现
（``_parse_ref`` / ``_evaluate_ref``）复制进本测试作对照。
"""
from pathlib import Path

from octagon_evals.calibration.metrics import GROUP_ORDER, aggregate, wilson_ci
from octagon_evals.calibration.report import render_report
from octagon_evals.calibration.rubricbench import (
    GROUP_LABELS,
    RUBRICBENCH_SYSTEM_PROMPT,
    build_user_prompt,
    domain_group,
    load_cases,
    normalize_group_selector,
    parse_verdict,
)
from octagon_evals.calibration.sampling import sample_cases

FIXTURE = Path(__file__).parents[1] / "fixtures/rubricbench_sample.json"


def _case(case_id, label, domain):
    return type("C", (), dict(case_id=case_id, label=label, domain=domain, group=domain_group(domain)))


# ---------- 官方 prompt ----------

def test_system_prompt_is_official():
    sp = RUBRICBENCH_SYSTEM_PROMPT
    assert "Impartial Judge" in sp and "Strict Evaluator" in sp
    assert "<Checklist>" in sp and "<Justification>" in sp
    assert "[[A]]" in sp and "[[B]]" in sp
    assert "MANDATORY NON-BIAS RULES" in sp


def test_build_user_prompt_injects_fields_in_order():
    case = _case("c1", 0, "code")
    case.instruction, case.rubrics, case.response_a, case.response_b = "inst", "check", "ra", "rb"
    up = build_user_prompt(case)
    assert up.startswith("[The User's Original <Instruction>]\ninst")
    assert "[The Evaluation <Checklist>]\ncheck" in up
    assert "[The Start of Assistant A's <Response>]\nra" in up
    assert "[The End of Assistant A's <Response>]" in up
    assert "[The Start of Assistant B's <Response>]\nrb" in up
    assert "[The End of Assistant B's <Response>]" in up
    # 注入原文，不做改写
    assert "check" in up and "inst" in up and "ra" in up and "rb" in up


# ---------- 裁决解析 ----------

def test_parse_verdict_forms():
    for text, want in [
        ("[[A]]", 0), ("[[B]]", 1), ("  [[A]]  ", 0),
        ("prose before ... [[B]] at the end", 1),
        ("A", 0), ("B", 1), ("0", 0), ("1", 1),
    ]:
        assert parse_verdict(text) == want, text


def test_parse_verdict_json_fallback():
    assert parse_verdict('{"winner": "B"}') == 1
    assert parse_verdict('{"winner": "A"}') == 0


def test_parse_verdict_invalid():
    assert parse_verdict(None) is None
    assert parse_verdict("") is None
    assert parse_verdict("sorry, I cannot decide") is None
    assert parse_verdict("[[C]]") is None


# ---------- 分组映射 ----------

def test_domain_group_mapping():
    assert domain_group("code") == "code"
    assert domain_group("ifeval") == "if"
    assert domain_group("precise if") == "if"
    assert domain_group("math") == "stem"
    assert domain_group("harmlessness") == "safety"
    assert domain_group("general") == "chat"
    assert domain_group("unknown-domain") is None


def test_normalize_group_selector():
    assert normalize_group_selector("CODE") == "code"
    assert normalize_group_selector("safe") == "safety"
    assert normalize_group_selector("IF") == "if"
    assert normalize_group_selector("chat") == "chat"
    assert normalize_group_selector("bogus") is None


# ---------- 加载 ----------

def test_load_cases_fixture():
    cases = load_cases(FIXTURE)
    assert len(cases) == 16
    assert all(c.label in (0, 1) for c in cases)
    assert all(c.rubrics for c in cases)
    groups = {GROUP_LABELS.get(c.group) for c in cases}
    assert groups == set(GROUP_ORDER)


# ---------- 抽样 ----------

def test_sampling_stratified_within_budget_and_balanced():
    cases = [_case(f"c{i}", i % 2, d) for i, d in enumerate(
        ["code", "code", "code", "code", "ifeval", "ifeval", "math", "safety", "general", "general"]
    )]
    selected, plan = sample_cases(cases, strategy="stratified", limit=6, seed=1)
    assert len(selected) == 6
    assert not plan.is_full
    # 不超预算、同种子可复现
    assert sum(plan.allocation.values()) == 6
    assert all(plan.allocation[g] <= sum(1 for c in cases if c.group == g) for g in plan.allocation)
    again, _ = sample_cases(cases, strategy="stratified", limit=6, seed=1)
    assert [c.case_id for c in selected] == [c.case_id for c in again]


def test_sampling_label_balance():
    cases = [_case(f"c{i}", i % 2, "code") for i in range(60)]
    selected, _ = sample_cases(cases, strategy="stratified", limit=10, seed=7)
    labels = [c.label for c in selected]
    assert 4 <= labels.count(0) <= 6 and 4 <= labels.count(1) <= 6


def test_sampling_full_and_auto_full():
    cases = [_case(f"c{i}", i % 2, "code") for i in range(5)]
    selected, plan = sample_cases(cases, strategy="full", limit=0, seed=1)
    assert len(selected) == 5 and plan.is_full and plan.strategy == "full"
    # limit 超过可用量自动转全量
    _, plan2 = sample_cases(cases, strategy="stratified", limit=100, seed=1)
    assert plan2.is_full and plan2.strategy == "full"
    assert len(plan2.allocation) == 1 and plan2.allocation["code"] == 5


def test_sampling_random():
    cases = [_case(f"c{i}", i % 2, "code") for i in range(20)]
    selected, plan = sample_cases(cases, strategy="random", limit=4, seed=3)
    assert len(selected) == 4 and plan.strategy == "random"
    again, _ = sample_cases(cases, strategy="random", limit=4, seed=3)
    assert [c.case_id for c in selected] == [c.case_id for c in again]


def test_sampling_domain_filter():
    cases = [_case(f"c{i}", i % 2, d) for i, d in enumerate(["code", "ifeval", "code", "math"])]
    selected, plan = sample_cases(cases, strategy="stratified", limit=4, seed=1, groups={"code"})
    assert {c.group for c in selected} == {"code"}
    assert len(selected) == 2 and plan.is_full


# ---------- Wilson 置信区间 ----------

def test_wilson_ci():
    lo, hi = wilson_ci(50, 100)
    assert 0.40 < lo < 0.42 and 0.58 < hi < 0.60
    # 10/10 的 Wilson 区间不是精确 [1,1]：下界约 0.72，上界裁剪到 1.0
    lo, hi = wilson_ci(10, 10)
    assert 0.70 < lo < 0.75 and hi == 1.0
    lo, hi = wilson_ci(0, 5)  # 下界裁剪到 0
    assert lo == 0.0 and 0.42 < hi < 0.45
    lo, hi = wilson_ci(0, 0)
    assert lo != lo and hi != hi  # nan


# ---------- 指标（与 rubricbench eval_submission 口径对照） ----------

REF_DOMAIN_GROUPS = {
    "chat": {"general", "focus", "human-preference", "factuality", "helpful"},
    "if": {"precise if", "ifeval"},
    "stem": {"stem", "math", "mmlu-pro", "gpqa"},
    "code": {"mbpp", "code"},
    "safety": {"safety", "harmlessness"},
}


def _group_ref(domain):
    d = str(domain).strip().lower()
    for group, members in REF_DOMAIN_GROUPS.items():
        if d in members:
            return group
    return None


def _parse_ref(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    upper = text.upper()
    if upper in {"A", "[[A]]", "0"}:
        return 0
    if upper in {"B", "[[B]]", "1"}:
        return 1
    import re
    matches = re.findall(r"\[\[([AB])\]\]", upper)
    if matches:
        return 0 if matches[-1] == "A" else 1
    return None


def _evaluate_ref(pred_by_id, benchmark):
    total = len(benchmark)
    correct = valid_pred = 0
    by_group = {g: [0, 0] for g in ("if", "stem", "code", "chat", "safety")}
    for case_id, meta in benchmark.items():
        group = meta["group"]
        if group in by_group:
            by_group[group][1] += 1
        pred = pred_by_id.get(case_id)
        if pred is None:
            continue
        valid_pred += 1
        if pred == meta["label"]:
            correct += 1
            if group in by_group:
                by_group[group][0] += 1
    return correct / total, correct / valid_pred if valid_pred else 0.0, by_group


def test_metrics_matches_reference_implementation():
    benchmark = {
        "a1": {"label": 0, "domain": "code"},
        "a2": {"label": 1, "domain": "code"},
        "a3": {"label": 1, "domain": "ifeval"},
        "a4": {"label": 0, "domain": "general"},
        "a5": {"label": 1, "domain": "safety"},
        "a6": {"label": 0, "domain": "math"},
    }
    for m in benchmark.values():
        m["group"] = _group_ref(m["domain"])
    # 预测：1 个对、1 个错、1 个 invalid，其余对
    pred_by_id = {"a1": 0, "a2": 0, "a3": None, "a4": 0, "a5": 1, "a6": 0}

    ref_acc, ref_valid_acc, ref_by_group = _evaluate_ref(pred_by_id, benchmark)
    records = [
        {"group": GROUP_LABELS[benchmark[cid]["group"]], "verdict": pred_by_id[cid], "gold": benchmark[cid]["label"]}
        for cid in benchmark
    ]
    rows = aggregate(records)
    overall = rows[0]
    assert overall.acc == ref_acc
    assert overall.valid_acc == ref_valid_acc
    # 分组 ACC 与参考逐组一致
    for row in rows[1:]:
        group_key = next(k for k, v in GROUP_LABELS.items() if v == row.group)
        c, t = ref_by_group[group_key]
        assert row.acc == (c / t if t else 0.0)
        assert row.total == t


def test_aggregate_invalid_counts_as_wrong():
    records = [
        {"group": "CODE", "verdict": 0, "gold": 0},
        {"group": "CODE", "verdict": None, "gold": 0},
    ]
    rows = aggregate(records)
    assert rows[0].acc == 0.5 and rows[0].invalid == 1
    assert len([r for r in rows if r.group == "CODE"]) == 1
