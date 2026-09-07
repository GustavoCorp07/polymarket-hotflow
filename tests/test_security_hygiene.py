import subprocess
from pathlib import Path

from hotflow.security.hygiene import env_example_secret_values


def test_env_example_has_no_live_secrets() -> None:
    text = Path(".env.example").read_text(encoding="utf-8")
    assert "HOTFLOW_ACCEPT_LIVE=0" in text
    assert "POLYMARKET_PRIVATE_KEY=" in text
    assert not any(line.split("=", 1)[-1].strip() for line in text.splitlines() if "PRIVATE_KEY=" in line)
    assert env_example_secret_values() == {}
    assert "KIMI_API_KEY=" in text
    assert "MOONSHOT_API_KEY=" in text


def test_src_has_no_embedded_pem() -> None:
    for path in Path("src").rglob("*.py"):
        blob = path.read_text(encoding="utf-8")
        assert "BEGIN" not in blob or "PRIVATE KEY" not in blob or "REDACTED" in blob


def test_repo_has_no_checked_in_pem_headers() -> None:
    """Same guard as CI secret hygiene — must not self-match the workflow file."""
    result = subprocess.run(
        [
            "git",
            "grep",
            "-nE",
            "-e",
            r"-----BEGIN ([A-Z0-9]+ )?PRIVATE KEY-----",
            "--",
            ":!.github",
            ":!docs",
            ":!tests/test_kimi.py",
            ":!src/hotflow/ai_research/kimi_client.py",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1, result.stdout or result.stderr
