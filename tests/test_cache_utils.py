import hashlib
from pathlib import Path

from fund_holdings_agent import manager_funds
from fund_holdings_agent.manager_funds import CachedFetcher


def test_corrupt_cache_is_quarantined_and_atomically_refreshed(tmp_path: Path, monkeypatch):
    url = "https://example.test/cache"
    cache = tmp_path / f"{hashlib.sha256(url.encode()).hexdigest()}.html"
    cache.write_bytes(b"\xff\xfe\x00bad")
    monkeypatch.setattr(manager_funds, "fetch_url", lambda *_args, **_kwargs: "fresh")

    value = CachedFetcher(tmp_path)(url)

    assert value == "fresh"
    assert cache.read_text(encoding="utf-8") == "fresh"
    assert len(list(tmp_path.glob("*.corrupt*"))) == 1
    assert not list(tmp_path.glob("*.tmp"))


def test_valid_cache_is_reused_without_fetch(tmp_path: Path, monkeypatch):
    url = "https://example.test/cache"
    cache = tmp_path / f"{hashlib.sha256(url.encode()).hexdigest()}.html"
    cache.write_text("valid", encoding="utf-8")

    def fail_fetch(*_args, **_kwargs):
        raise AssertionError("不应联网")

    monkeypatch.setattr(manager_funds, "fetch_url", fail_fetch)
    assert CachedFetcher(tmp_path)(url) == "valid"
