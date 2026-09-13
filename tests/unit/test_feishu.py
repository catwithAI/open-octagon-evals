import pytest
from octagon_evals.adapters.feishu import FeishuConfig

def test_feishu_config_requires_runtime_secrets(monkeypatch):
    monkeypatch.delenv("FEISHU_APP_ID", raising=False); monkeypatch.delenv("FEISHU_APP_SECRET", raising=False)
    with pytest.raises(RuntimeError): FeishuConfig.from_env()

def test_feishu_config_reads_env(monkeypatch):
    monkeypatch.setenv("FEISHU_APP_ID", "cli-test"); monkeypatch.setenv("FEISHU_APP_SECRET", "secret-test")
    assert FeishuConfig.from_env().app_id == "cli-test"
