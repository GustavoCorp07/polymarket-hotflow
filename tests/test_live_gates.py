"""Phase 15: LIVE gates stay closed; no signing surface on the paper path."""

import ast
from pathlib import Path

from typer.testing import CliRunner

from hotflow.cli import app
from hotflow.config import load_config
from hotflow.execution.live_executor import SIGNING_IMPLEMENTED, LiveExecutor
from hotflow.execution.live_gate import (
    LiveGateError,
    assert_live_allowed,
    inspect_live_gates,
    live_gates_open,
    require_live_closed,
)
from hotflow.pipeline import PaperPipeline, demo_market
from hotflow.security.hygiene import PLACEHOLDER_ENV_KEYS, env_example_secret_values


def test_default_gates_closed() -> None:
    cfg = load_config("configs/default.yaml")
    report = inspect_live_gates(cfg, environ={})
    assert cfg.trading.mode == "paper"
    assert cfg.live.accept_live_trading is False
    assert cfg.live.accept_capital_at_risk is False
    assert cfg.live.i_understand_orders_are_real is False
    assert report.live_gates_open is False
    assert report.freeze_ok is True
    assert report.signing_implemented is False
    assert SIGNING_IMPLEMENTED is False
    require_live_closed(cfg, environ={})


def test_refuse_live_without_all_flags(monkeypatch) -> None:
    cfg = load_config("configs/default.yaml")
    cfg.trading.mode = "live"
    cfg.live.accept_live_trading = True
    cfg.live.accept_capital_at_risk = True
    cfg.live.i_understand_orders_are_real = True
    monkeypatch.delenv("HOTFLOW_ACCEPT_LIVE", raising=False)
    assert live_gates_open(cfg) is False
    try:
        assert_live_allowed(cfg)
        raise AssertionError("missing env must refuse")
    except LiveGateError:
        pass
    monkeypatch.setenv("HOTFLOW_ACCEPT_LIVE", "1")
    assert live_gates_open(cfg) is True
    # Signing still refuses even if acceptance gates are forced open.
    try:
        LiveExecutor(cfg).place_order({"token_id": "x"})
        raise AssertionError("signing must stay unimplemented")
    except LiveGateError as exc:
        assert "not implemented" in str(exc)


def test_paper_executor_refuses_all_methods() -> None:
    cfg = load_config("configs/default.yaml")
    exe = LiveExecutor(cfg)
    for method in ("place_order", "cancel_order", "get_positions", "get_orders"):
        try:
            getattr(exe, method)()
            raise AssertionError(method)
        except LiveGateError as exc:
            assert "LIVE gates closed" in str(exc)
    try:
        exe.execute_arbitrary_transaction()
        raise AssertionError("arbitrary tx")
    except LiveGateError:
        pass


def test_evaluate_does_not_call_live_executor() -> None:
    cfg = load_config("configs/default.yaml")
    pipe = PaperPipeline(cfg)
    result = pipe.evaluate_market(demo_market(hot=True), p_info=0.70)
    assert result["accepted"] is True
    assert not hasattr(pipe, "live_executor")
    assert "order" in result
    assert result["order"].get("mode") == "paper"


def test_hot_path_has_no_signing_surface() -> None:
    forbidden = (
        "eip712",
        "eth_account",
        "sign_order",
        "load_pem",
        "private_key",
        "POLYMARKET_PRIVATE_KEY",
        "hmac.new",
    )
    roots = [
        Path("src/hotflow/pipeline.py"),
        Path("src/hotflow/execution/paper.py"),
        Path("src/hotflow/execution/orders.py"),
        Path("src/hotflow/portfolio"),
        Path("src/hotflow/risk"),
    ]
    files: list[Path] = []
    for root in roots:
        if root.is_file():
            files.append(root)
        else:
            files.extend(root.rglob("*.py"))
    for path in files:
        blob = path.read_text(encoding="utf-8").lower()
        for token in forbidden:
            assert token.lower() not in blob, f"{path} contains {token}"
    for path in Path("src/hotflow/execution").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = [
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        ]
        assert not any(mod and "ai_research" in mod for mod in imports)


def test_cli_live_gates_closed(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("HOTFLOW_ACCEPT_LIVE", raising=False)
    monkeypatch.delenv("HOTFLOW_TRADING_MODE", raising=False)
    out = tmp_path / "live-gates.json"
    result = CliRunner().invoke(app, ["live-gates", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert "live_gates_open=False" in result.output
    assert "freeze_ok=True" in result.output
    assert "signing_implemented=False" in result.output
    for name in (
        "trading.mode=CLOSED",
        "live.accept_live_trading=CLOSED",
        "HOTFLOW_ACCEPT_LIVE=CLOSED",
    ):
        assert name in result.output
    import json

    body = json.loads(out.read_text(encoding="utf-8"))
    assert body["freeze_ok"] is True
    assert body["live_gates_open"] is False


def test_cli_live_gates_exits_when_open(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOTFLOW_ACCEPT_LIVE", "1")
    cfg_path = tmp_path / "live.yaml"
    cfg_path.write_text(
        Path("configs/default.yaml").read_text(encoding="utf-8").replace(
            "mode: paper", "mode: live"
        ).replace("accept_live_trading: false", "accept_live_trading: true")
        .replace("accept_capital_at_risk: false", "accept_capital_at_risk: true")
        .replace(
            "i_understand_orders_are_real: false",
            "i_understand_orders_are_real: true",
        ),
        encoding="utf-8",
    )
    result = CliRunner().invoke(app, ["live-gates", "--config", str(cfg_path)])
    assert result.exit_code == 1, result.output
    assert "live_gates_open=True" in result.output
    assert "freeze_ok=False" in result.output


def test_env_example_placeholders_only() -> None:
    filled = env_example_secret_values()
    assert filled == {}
    text = Path(".env.example").read_text(encoding="utf-8")
    assert "HOTFLOW_ACCEPT_LIVE=0" in text
    assert "cold-path" in text.lower() or "never on decide" in text.lower()
    for key in PLACEHOLDER_ENV_KEYS:
        assert f"{key}=" in text
