from __future__ import annotations

from btcpoly.config import load_settings
from btcpoly.ingestion.agent_reach.doctor import check_agent_reach


def test_agent_reach_missing_is_not_fatal(monkeypatch, default_config_path) -> None:
    monkeypatch.setattr(
        "btcpoly.ingestion.agent_reach.doctor.shutil.which",
        lambda _name: None,
    )
    settings = load_settings(default_config_path, env={}, load_dotenv_file=False)
    health = check_agent_reach(settings)
    assert health.installed is False
    assert health.ok is False
    assert "not on PATH" in health.message
