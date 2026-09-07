from __future__ import annotations

import json
from pathlib import Path

from hotflow.monitoring.pages_demo import (
    DEMO_NOTICE,
    EXPECTED_STATE_KEYS,
    SECRET_NEEDLES,
    state_errors,
    write_pages_demo,
)

PAGES = Path("docs/pages")
REQUIRED_STATIC = (
    "index.html",
    "README.md",
    ".nojekyll",
    "demo-state.json",
    "state.json",
    "snapshots.json",
    "demo-bundle.js",
    "assets/dashboard.css",
    "assets/pages.js",
)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_pages_static_files_exist() -> None:
    for rel in REQUIRED_STATIC:
        path = PAGES / rel
        assert path.is_file(), rel
        if rel != ".nojekyll":
            assert path.stat().st_size > 0, rel
    snaps = sorted((PAGES / "snapshots").glob("*.json"))
    assert 2 <= len(snaps) <= 4


def test_pages_html_is_static_demo_not_live_sse() -> None:
    html = (PAGES / "index.html").read_text(encoding="utf-8")
    js = (PAGES / "assets/pages.js").read_text(encoding="utf-8")
    css = (PAGES / "assets/dashboard.css").read_text(encoding="utf-8")
    assert "HOTFLOW" in html
    assert "PAPER" in html
    assert DEMO_NOTICE.split("—")[0].strip() in html
    assert "hotflow dashboard" in html
    assert "state.json" in html or "state.json" in js
    assert "EventSource" not in html
    assert "EventSource" not in js
    assert "/events" not in js
    assert "api_key" not in html.lower()
    assert "PRIVATE KEY" not in html
    assert "HOTFLOW_ACCEPT_LIVE" not in html
    assert "--bg:" in css
    assert "--paper:" in css


def test_committed_demo_json_matches_api_state_shape() -> None:
    primary = _read_json(PAGES / "demo-state.json")
    poll = _read_json(PAGES / "state.json")
    manifest = _read_json(PAGES / "snapshots.json")
    assert not state_errors(primary), state_errors(primary)
    assert not state_errors(poll), state_errors(poll)
    assert EXPECTED_STATE_KEYS <= set(primary)
    assert primary["ledger"]["origin"] == "paper_ledger"
    assert primary["live_gates"]["closed"] is True
    assert primary["mode"] == "paper"
    assert primary["kill_switch"]["tripped"] is False
    assert primary["health"]["ready"] is True
    assert poll["generation"] == primary["generation"]
    assert manifest["poll"] == "state.json"
    assert manifest["static_pages_demo"] is True
    assert isinstance(manifest["rotate"], list)
    assert 2 <= len(manifest["rotate"]) <= 4
    for rel in manifest["rotate"]:
        frame = _read_json(PAGES / rel)
        assert not state_errors(frame), (rel, state_errors(frame))
        assert frame["recent"]
        decisions = {row["decision"] for row in frame["recent"]}
        assert decisions <= {"TRADE", "SKIP", "SHADOW"}


def test_pages_demo_has_no_env_or_secrets() -> None:
    assert not (PAGES / ".env").exists()
    assert not Path(".env").exists()
    blobs = [PAGES.joinpath(rel).read_text(encoding="utf-8", errors="replace") for rel in REQUIRED_STATIC]
    blobs.extend(path.read_text(encoding="utf-8") for path in (PAGES / "snapshots").glob("*.json"))
    joined = "\n".join(blobs)
    for needle in SECRET_NEEDLES:
        assert needle not in joined
    assert "-----" + "BEGIN" not in joined
    assert "POLYMARKET_PRIVATE_KEY=" not in joined


def test_export_pages_demo_writes_valid_tree(tmp_path: Path) -> None:
    sqlite = tmp_path / "demo.sqlite"
    written = write_pages_demo(tmp_path, cycles=2, flatten=True, sqlite_path=sqlite)
    assert (tmp_path / "demo-state.json").is_file()
    assert (tmp_path / "state.json").is_file()
    assert (tmp_path / "snapshots.json").is_file()
    assert (tmp_path / "demo-bundle.js").is_file()
    assert "demo-state.json" in written
    manifest = _read_json(tmp_path / "snapshots.json")
    assert len(manifest["rotate"]) == 3
    latest = _read_json(tmp_path / "demo-state.json")
    assert not state_errors(latest), state_errors(latest)
    assert latest["cycle_count"] >= 1
    assert latest["ledger"]["equity"] is not None
    assert latest["kill_switch"]["tripped"] is False
    assert latest["live_gates"]["closed"] is True
    bundle = (tmp_path / "demo-bundle.js").read_text(encoding="utf-8")
    assert bundle.startswith("window.HOTFLOW_PAGES_DEMO = ")
    assert "api_key" not in bundle.lower() or '"api_key"' not in bundle
    assert "PRIVATE KEY" not in bundle
