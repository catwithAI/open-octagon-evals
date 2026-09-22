"""归因角色：prompt 三段块、parse/schema 校验、category 白名单。"""
import pytest

from octagon_evals.attribution.role import (
    ATTRIBUTION_SCHEMA_VERSION,
    ATTRIBUTION_SYSTEM_PROMPT,
    build_user_prompt,
    parse_attribution,
)
from octagon_evals.errors import InvalidJudgeOutput
from octagon_evals.models import Dimension, DimensionScore


def _dim():
    return Dimension(
        "execution_quality", method="agent_judge", question="评估质量",
        anchors=[{"score": 0.0, "label": "bad", "description": "没有核对"},
                 {"score": 1.0, "label": "good", "description": "完成核对"}],
    )


def _score(value=0.2, reason="没有核对"):
    return DimensionScore("t1", value, "agent_judge", reason=reason, lineage={"model": "m"})


def test_system_prompt_has_discipline():
    sp = ATTRIBUTION_SYSTEM_PROMPT
    assert "PHENOMENON" in sp and "ROOT CAUSES" in sp and "SUGGESTIONS" in sp
    assert "agent_behavior" in sp and "insufficient_evidence" in sp
    assert "candidate" in sp  # candidate-only
    assert "CANDIDATE for human review" in sp


def test_build_user_prompt_three_blocks():
    up = build_user_prompt(_dim(), _score(), {"location": "evidence.json / evidence/"})
    assert "# 被评维度（rubric）" in up
    assert "# 分数与 judge 理由" in up
    assert "# 行为证据" in up
    assert "execution_quality" in up and "评估质量" in up
    assert "没有核对" in up and "0.2" in up
    assert "evidence.json" in up
    # 锚点渲染
    assert "bad" in up and "good" in up


def _valid(phenomenon="p"):
    return {
        "schema_version": ATTRIBUTION_SCHEMA_VERSION, "status": "candidate",
        "phenomenon": phenomenon,
        "root_causes": [{"category": "agent_behavior", "description": "d", "confidence": "high"}],
        "suggestions": [{"target": "agent", "action": "a", "rationale": "r"}], "notes": [],
    }


def test_parse_valid_fenced():
    import json
    att = parse_attribution("```json\n" + json.dumps(_valid("phenomenon")) + "\n```")
    assert att["phenomenon"] == "phenomenon"
    assert att["root_causes"][0]["category"] == "agent_behavior"


def test_parse_all_root_categories_allowed():
    import json
    for cat in ("agent_behavior", "rubric", "evidence", "workflow", "insufficient_evidence"):
        att = _valid()
        att["root_causes"] = [{"category": cat, "description": "d", "confidence": "low"}]
        parsed = parse_attribution(json.dumps(att))
        assert parsed["root_causes"][0]["category"] == cat


def test_parse_rejects_invalid():
    import json
    cases = []
    att = _valid(); att["schema_version"] = "x"; cases.append(json.dumps(att))
    att = _valid(); att["status"] = "final"; cases.append(json.dumps(att))
    att = _valid(); att["phenomenon"] = ""; cases.append(json.dumps(att))
    att = _valid(); att["root_causes"] = [{"category": "bogus", "description": "d", "confidence": "high"}]; cases.append(json.dumps(att))
    att = _valid(); att["suggestions"] = [{"target": "bogus", "action": "a"}]; cases.append(json.dumps(att))
    att = _valid(); att["root_causes"] = [{"category": "rubric", "description": "d", "confidence": "extreme"}]; cases.append(json.dumps(att))
    for text in cases:
        with pytest.raises(InvalidJudgeOutput):
            parse_attribution(text)


def test_parse_rejects_non_json():
    with pytest.raises(InvalidJudgeOutput):
        parse_attribution("I think the phenomenon is that the agent failed.")


def test_parse_requires_root_causes_list():
    import json
    att = _valid(); att["root_causes"] = "not-a-list"
    with pytest.raises(InvalidJudgeOutput):
        parse_attribution(json.dumps(att))
