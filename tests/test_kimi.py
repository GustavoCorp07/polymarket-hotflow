from hotflow.ai_research.kimi_client import KimiClient, KimiRole, redact
from hotflow.config import AIResearchConfig


def test_mock_without_key(monkeypatch) -> None:
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    client = KimiClient(AIResearchConfig(), api_key=None)
    out = client.complete(KimiRole.QUANT_RESEARCHER, "Summarize edge accounting.")
    assert out["mock"] is True
    assert out["role"] == "QUANT_RESEARCHER"


def test_transport_mock_and_redaction() -> None:
    captured: dict = {}

    def transport(payload: dict) -> dict:
        captured.update(payload)
        return {"content": "ok"}

    client = KimiClient(transport=transport, api_key="should-not-be-sent-to-prompt")
    text = "POLY_API_KEY=abcd private_key=0xdead"
    result = client.complete(KimiRole.CODE_REVIEWER, text)
    assert result["content"] == "ok"
    user = captured["messages"][1]["content"]
    assert "abcd" not in user
    assert "0xdead" not in user
    assert "[REDACTED]" in user
    assert captured["model"] == "kimi-k3"
    assert captured["reasoning_effort"] == "high"


def test_hard_task_uses_max() -> None:
    def transport(payload: dict) -> dict:
        return payload

    client = KimiClient(transport=transport)
    payload = client.complete(KimiRole.ANOMALY_INVESTIGATOR, "why reject streak?", hard=True)
    assert payload["reasoning_effort"] == "max"


def test_redact_pem() -> None:
    blob = "-----BEGIN EC PRIVATE KEY-----\nABC\n-----END EC PRIVATE KEY-----"
    assert "BEGIN" not in redact(blob) or "[REDACTED]" in redact(blob)


def test_all_roles_have_prompts() -> None:
    client = KimiClient(transport=lambda p: p)
    for role in KimiRole:
        payload = client.complete(role, "ping")
        assert payload["messages"][0]["content"]
