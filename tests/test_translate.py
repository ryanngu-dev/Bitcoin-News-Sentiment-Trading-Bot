from __future__ import annotations

from btcpoly.text.translate import has_cjk, translate_to_english


def test_has_cjk() -> None:
    assert has_cjk("比特币突破新高") is True
    assert has_cjk("Bitcoin hits a new high") is False
    assert has_cjk("") is False


def test_translate_skips_english() -> None:
    assert translate_to_english("Bitcoin ETF inflows rise") == "Bitcoin ETF inflows rise"


def test_translate_uses_google_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        "btcpoly.text.translate._http_json",
        lambda url, timeout: [[["Bitcoin hits a new high", "比特币突破新高", None, None, 0]]],
    )
    assert translate_to_english("比特币突破新高") == "Bitcoin hits a new high"
