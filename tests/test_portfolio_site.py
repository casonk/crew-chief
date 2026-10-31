"""The vendored portfolio seam: its fallback copy is intact and answers when nothing else does."""

import hashlib
from pathlib import Path

import pytest

from crew_chief.portfolio import site as portfolio_site

ROOT = Path(__file__).resolve().parents[1]
VENDORED = ROOT / "src/crew_chief/portfolio"


def test_manifest_pins_every_vendored_file():
    lines = (VENDORED / "MANIFEST.sha256").read_text().splitlines()
    names = set()
    for line in lines:
        digest, name = line.split("  ", 1)
        names.add(name)
        assert hashlib.sha256((VENDORED / name).read_bytes()).hexdigest() == digest, name
    assert names == {"__init__.py", "site.py", "theme.css", "theme.js", "chrome.js"}


def test_the_fallback_answers_with_no_store_and_serves_only_the_allowlist(tmp_path):
    site = portfolio_site.resolve(
        tmp_path, vendored=VENDORED, env={portfolio_site.STORE_ENV: str(tmp_path / "none")}
    )
    assert site.response("/_portfolio/theme.css")[0] == (VENDORED / "theme.css").read_bytes()
    assert site.response("/_portfolio/chrome.js")[0] == (VENDORED / "chrome.js").read_bytes()
    assert site.response("/_portfolio/nav.json")[0] == portfolio_site.EMPTY_NAV
    for path in ("/_portfolio/site.py", "/_portfolio/MANIFEST.sha256", "/_portfolio/../site.py"):
        assert site.response(path) is None


def test_the_example_config_is_synthetic_and_valid():
    tomllib = pytest.importorskip("tomllib")
    text = (ROOT / "config" / "portfolio-site.example.toml").read_text()
    settings = tomllib.loads(text)["site"]
    assert settings["fronting"] in portfolio_site.FRONTING
    assert set(settings) == {"fronting"}


def test_the_bench_interface_serves_the_portfolio_files_itself(tmp_path, monkeypatch):
    import threading
    import urllib.error
    import urllib.request

    from crew_chief import benchui
    from crew_chief.portfolio import site as portfolio_site

    monkeypatch.setenv(portfolio_site.STORE_ENV, str(tmp_path / "no-store"))
    results = tmp_path / "results"
    results.mkdir()
    server = benchui.make_server(tmp_path / "state", results, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urllib.request.urlopen(base + "/_portfolio/theme.css") as resp:
            assert resp.status == 200
            assert resp.read() == (VENDORED / "theme.css").read_bytes()
        with urllib.request.urlopen(base + "/_portfolio/nav.json") as resp:
            assert resp.read() == portfolio_site.EMPTY_NAV
        for path in ("/_portfolio/site.py", "/_portfolio/nope"):
            try:
                urllib.request.urlopen(base + path)
            except urllib.error.HTTPError as err:
                assert err.code == 400  # the interface reports a refused request as 400
            else:
                raise AssertionError(path)
    finally:
        server.shutdown()
        server.server_close()
