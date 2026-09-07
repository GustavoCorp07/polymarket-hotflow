from pathlib import Path


def test_env_example_has_no_live_secrets() -> None:
    text = Path(".env.example").read_text(encoding="utf-8")
    assert "HOTFLOW_ACCEPT_LIVE=0" in text
    assert "POLYMARKET_PRIVATE_KEY=" in text
    assert not any(line.split("=", 1)[-1].strip() for line in text.splitlines() if "PRIVATE_KEY=" in line)


def test_src_has_no_embedded_pem() -> None:
    for path in Path("src").rglob("*.py"):
        blob = path.read_text(encoding="utf-8")
        assert "BEGIN" not in blob or "PRIVATE KEY" not in blob or "REDACTED" in blob
