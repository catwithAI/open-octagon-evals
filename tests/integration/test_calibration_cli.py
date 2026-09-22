"""calibration CLI 全链路：抽样、判judge、幂等落库、续跑、报告渲染。

用 fake pi runner / fake opener 注入，不依赖仓库外 rubricbench 数据。
"""
import json
from pathlib import Path

from octagon_evals.calibration import cli
from octagon_evals.calibration.judge import JudgeTransport
from octagon_evals.judge_service.config import JudgeServiceConfig
from octagon_evals.scorers.agent_judge import AgentJudgeConfig

FIXTURE = Path(__file__).parents[1] / "fixtures/rubricbench_sample.json"


def _event_stream(text):
    events = [
        {"type": "turn_end", "message": {"role": "assistant", "content": [{"type": "text", "text": text}], "toolResults": []}},
        {"type": "agent_end", "messages": [{"role": "assistant", "content": [{"type": "text", "text": text}]}]},
    ]
    return "\n".join(json.dumps(e) for e in events)


class _FakeCompletedProcess:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


def make_agentic_transport():
    """fake judge：恒回 [[B]]（verdict 1），遇到 force-invalid 探针无裁决。"""
    def runner(cmd, **kwargs):
        prompt = cmd[-1]
        if "force-invalid" in prompt:
            return _FakeCompletedProcess(_event_stream("sorry, I cannot decide."))
        return _FakeCompletedProcess(_event_stream("[[B]]"))
    config = JudgeServiceConfig(pi_bin="pi")
    return JudgeTransport(agentic_config=config, subprocess_runner=runner)


class _FakeResponse:
    def __init__(self, body): self.body = body
    def read(self): return self.body
    def __enter__(self): return self
    def __exit__(self, *exc): return False


def make_inline_transport():
    class FakeOpener:
        def __call__(self, request, **kwargs):
            body = json.dumps({"choices": [{"message": {"content": "[[A]]"}}]}).encode()
            return _FakeResponse(body)
    config = AgentJudgeConfig(endpoint="https://example.test/v1/chat/completions", model="judge-m")
    return JudgeTransport(inline_config=config, opener=FakeOpener())


def _nolog(*args, **kwargs):
    pass


def test_cli_full_pipeline_writes_verdicts_and_report(tmp_path):
    transport = make_agentic_transport()
    verdicts = tmp_path / "verdicts.jsonl"
    out = tmp_path / "report.md"
    code = cli.main(
        ["--data", str(FIXTURE), "--backend", "agentic", "--strategy", "full",
         "--verdicts", str(verdicts), "--out", str(out)],
        transport=transport, log=_nolog,
    )
    assert code == 0
    assert len(verdicts.read_text().splitlines()) == 16  # fixture 全量
    report = out.read_text()
    assert "Judge 校准报告" in report and "Overall" in report
    # fake 恒回 [[B]]：gold=1 的 8 条对，gold=0 全错（含 1 条 invalid）
    assert "ACC = **0.5000**" in report
    assert "invalid = 1" in report
    assert transport.calls == 16


def test_cli_stratified_sample(tmp_path):
    transport = make_agentic_transport()
    verdicts = tmp_path / "verdicts.jsonl"
    out = tmp_path / "report.md"
    code = cli.main(
        ["--data", str(FIXTURE), "--backend", "agentic", "--strategy", "stratified",
         "--limit", "6", "--seed", "1", "--verdicts", str(verdicts), "--out", str(out)],
        transport=transport, log=_nolog,
    )
    assert code == 0
    assert len(verdicts.read_text().splitlines()) == 6
    report = out.read_text()
    assert "抽样策略：**stratified**，limit=6，seed=1" in report
    assert "95% CI" in report
    assert transport.calls == 6


def test_cli_resume_is_idempotent(tmp_path):
    verdicts = tmp_path / "verdicts.jsonl"
    out = tmp_path / "report.md"
    args = ["--data", str(FIXTURE), "--backend", "agentic", "--strategy", "full",
            "--verdicts", str(verdicts), "--out", str(out)]
    first = make_agentic_transport()
    cli.main(args, transport=first, log=_nolog)
    assert first.calls == 16

    second = make_agentic_transport()
    cli.main(args, transport=second, log=_nolog)
    assert second.calls == 0  # 全部复用，不再判
    assert len(verdicts.read_text().splitlines()) == 16


def test_cli_force_rejudges(tmp_path):
    verdicts = tmp_path / "verdicts.jsonl"
    out = tmp_path / "report.md"
    args = ["--data", str(FIXTURE), "--backend", "agentic", "--strategy", "full",
            "--verdicts", str(verdicts), "--out", str(out)]
    cli.main(args, transport=make_agentic_transport(), log=_nolog)
    cli.main(args + ["--force"], transport=make_agentic_transport(), log=_nolog)
    assert len(verdicts.read_text().splitlines()) == 32


def test_cli_domains_filter(tmp_path):
    transport = make_agentic_transport()
    verdicts = tmp_path / "verdicts.jsonl"
    out = tmp_path / "report.md"
    cli.main(
        ["--data", str(FIXTURE), "--backend", "agentic", "--strategy", "full",
         "--domains", "code", "--verdicts", str(verdicts), "--out", str(out)],
        transport=transport, log=_nolog,
    )
    records = [json.loads(line) for line in verdicts.read_text().splitlines()]
    assert len(records) == 4  # code 组：code×3 + mbpp×1
    assert all(r["group"] == "CODE" for r in records)


def test_cli_inline_backend(tmp_path):
    transport = make_inline_transport()
    verdicts = tmp_path / "verdicts.jsonl"
    out = tmp_path / "report.md"
    code = cli.main(
        ["--data", str(FIXTURE), "--backend", "inline", "--strategy", "full",
         "--verdicts", str(verdicts), "--out", str(out)],
        transport=transport, log=_nolog,
    )
    assert code == 0
    records = [json.loads(line) for line in verdicts.read_text().splitlines()]
    assert len(records) == 16
    assert all(r["backend"] == "inline" for r in records)
    # inline fake 恒回 [[A]]（verdict 0）：gold=0 的 8 条对，gold=1 的 8 条错
    correct = sum(1 for r in records if r["correct"])
    assert correct == 8


def test_cli_concurrency_thread_safe(tmp_path):
    transport = make_agentic_transport()
    verdicts = tmp_path / "verdicts.jsonl"
    out = tmp_path / "report.md"
    code = cli.main(
        ["--data", str(FIXTURE), "--backend", "agentic", "--strategy", "full",
         "--concurrency", "4", "--verdicts", str(verdicts), "--out", str(out)],
        transport=transport, log=_nolog,
    )
    assert code == 0
    assert len(verdicts.read_text().splitlines()) == 16  # 并发下逐条完整落库
    assert transport.calls == 16  # 线程安全计数
    records = [json.loads(line) for line in verdicts.read_text().splitlines()]
    assert len(records) == len({r["case_id"] for r in records})  # 无重复 case
