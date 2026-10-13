from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from btcpoly.config import DEFAULT_CONFIG_PATH, load_settings
from btcpoly.db.session import init_db, reset_engine
from btcpoly.ingestion.pipeline import clear_channel_skips


@pytest.fixture(autouse=True)
def _clear_ingest_skips() -> None:
    clear_channel_skips()
    yield
    clear_channel_skips()


@pytest.fixture()
def default_config_path() -> Path:
    return DEFAULT_CONFIG_PATH


@pytest.fixture()
def settings(default_config_path: Path):
    return load_settings(
        default_config_path,
        env={"BTC_POLY_LIVE_TRADING": "0"},
        load_dotenv_file=False,
    )


@pytest.fixture()
def memory_db(settings):
    reset_engine()
    engine = init_db(settings, url="sqlite:///:memory:")
    yield engine
    reset_engine()


@pytest.fixture()
def tmp_yaml_config(tmp_path: Path) -> Path:
    source = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    source["execution"]["enabled"] = False
    source["database"]["url"] = "sqlite:///:memory:"
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(source), encoding="utf-8")
    return path
