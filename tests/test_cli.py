"""CLI: transports and remote-binding refusal, the auth helpers, purge and describe."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import click
import pytest
from click.testing import CliRunner

from microsoft_ads_mcp import cli


class _FakeServer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def run(self, transport: str, **kwargs: Any) -> None:
        self.calls.append((transport, kwargs))


@pytest.fixture
def base_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("MICROSOFT_ADS_CLIENT_ID", "00001111-aaaa-2222-bbbb-3333cccc4444")
    monkeypatch.setenv("MICROSOFT_ADS_DEVELOPER_TOKEN", "cli-dev-token-value")
    monkeypatch.setenv("MICROSOFT_ADS_CLIENT_SECRET", "cli-secret-value")
    monkeypatch.setenv("MICROSOFT_ADS_REFRESH_TOKEN", "cli-refresh-value")
    return tmp_path


@pytest.fixture
def fake_run(base_env: Path, monkeypatch: pytest.MonkeyPatch):
    server = _FakeServer()
    monkeypatch.setattr(cli, "build_server", lambda config: server)
    warnings: list[str] = []
    monkeypatch.setattr(cli.logger, "warning", lambda msg, *args: warnings.append(msg % args))

    def invoke(*args: str, ok: bool = True):
        env_file = str(base_env / "missing.env")
        result = CliRunner().invoke(cli.cli, ["--env", env_file, *args, "run"], obj={})
        if ok:
            assert result.exit_code == 0, result.output
        return server.calls, warnings, result

    return invoke


def test_stdio_is_the_default(fake_run) -> None:
    calls, warnings, _ = fake_run()
    assert calls == [("stdio", {})]
    assert warnings == []


def test_streamable_http_gets_host_and_port(fake_run) -> None:
    calls, _, _ = fake_run("--transport", "streamable-http", "--port", "9123")
    assert calls == [("streamable-http", {"host": "127.0.0.1", "port": 9123})]


def test_non_loopback_host_is_refused(fake_run) -> None:
    calls, _, result = fake_run("--transport", "streamable-http", "--host", "0.0.0.0", ok=False)
    assert result.exit_code != 0
    assert "MICROSOFT_ADS_ALLOW_REMOTE" in result.output
    assert calls == []


def test_non_loopback_allowed_with_flag_warns(fake_run) -> None:
    calls, warnings, _ = fake_run(
        "--transport", "streamable-http", "--host", "0.0.0.0", "--allow-remote"
    )
    assert calls == [("streamable-http", {"host": "0.0.0.0", "port": 8000})]
    assert any("no authentication" in w for w in warnings)


def test_non_loopback_allowed_with_env(fake_run, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MICROSOFT_ADS_ALLOW_REMOTE", "true")
    calls, _, _ = fake_run("--transport", "streamable-http", "--host", "10.0.0.5")
    assert calls[0][1]["host"] == "10.0.0.5"


def test_authorization_url() -> None:
    url = cli.authorization_url(
        authorize_url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        client_id="cid",
        redirect_uri="http://localhost:8765/callback",
        state="st",
        code_challenge="ch",
    )
    parsed = urlparse(url)
    assert parsed.netloc == "login.microsoftonline.com"
    q = parse_qs(parsed.query)
    assert q["scope"] == ["https://ads.microsoft.com/msads.manage offline_access"]
    assert q["response_type"] == ["code"]
    assert q["code_challenge_method"] == ["S256"]
    assert q["state"] == ["st"]


def test_parse_redirect_requires_matching_state() -> None:
    base = "https://login.microsoftonline.com/common/oauth2/nativeclient"
    assert cli.parse_redirect(f"{base}?code=ABC&state=st", "st") == "ABC"
    assert cli.parse_redirect("  ABC  ", "st") == "ABC"
    with pytest.raises(click.ClickException, match="no state"):
        cli.parse_redirect(f"{base}?code=ABC", "st")
    with pytest.raises(click.ClickException, match="doesn't match"):
        cli.parse_redirect(f"{base}?code=ABC&state=other", "st")
    with pytest.raises(click.ClickException, match="access_denied"):
        cli.parse_redirect(f"{base}?error=access_denied&state=st", "st")


def test_auth_manual_flow_saves_token_without_printing_it(
    base_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli.secrets, "token_urlsafe", lambda n: "fixedstate")
    seen: dict[str, Any] = {}

    def fake_exchange(**kwargs: Any) -> dict[str, Any]:
        seen.update(kwargs)
        return {"refresh_token": "brand-new-refresh", "access_token": "x"}

    monkeypatch.setattr(cli, "exchange_code", fake_exchange)
    result = CliRunner().invoke(
        cli.cli,
        ["--env", str(base_env / "missing.env"), "auth", "--manual", "--no-browser"],
        input="https://login.microsoftonline.com/common/oauth2/nativeclient?code=THECODE&state=fixedstate\n",
        obj={},
    )
    assert result.exit_code == 0, result.output
    assert seen["code"] == "THECODE"
    assert seen["redirect_uri"] == "https://login.microsoftonline.com/common/oauth2/nativeclient"
    assert seen["code_verifier"]
    assert seen["client_secret"] == "cli-secret-value"
    token_file = base_env / "home" / "secrets" / "microsoft-ads-token.json"
    data = json.loads(token_file.read_text())
    assert data["refresh_token"] == "brand-new-refresh"
    assert data["environment"] == "production"
    assert "brand-new-refresh" not in result.output
    assert "cli-secret-value" not in result.output


def test_purge_deletes_audit_and_token(base_env: Path) -> None:
    home = base_env / "home"
    audit = home / "logs" / "audit.jsonl"
    token = home / "secrets" / "microsoft-ads-token.json"
    audit.parent.mkdir(parents=True)
    token.parent.mkdir(parents=True)
    audit.write_text("{}\n")
    token.write_text("{}")
    result = CliRunner().invoke(
        cli.cli, ["--env", str(base_env / "missing.env"), "purge", "--yes"], obj={}
    )
    assert result.exit_code == 0, result.output
    assert not audit.exists() and not token.exists()


def test_describe_hides_secrets(base_env: Path) -> None:
    result = CliRunner().invoke(
        cli.cli, ["--env", str(base_env / "missing.env"), "describe"], obj={}
    )
    assert result.exit_code == 0, result.output
    for secret in ("cli-secret-value", "cli-refresh-value", "cli-dev-token-value"):
        assert secret not in result.output
    info = json.loads(result.output)
    assert info["refresh_token"].startswith("set")
    assert info["developer_token"] == "set"


def test_unknown_transport_is_rejected() -> None:
    result = CliRunner().invoke(cli.cli, ["--transport", "websocket", "run"], obj={})
    assert result.exit_code != 0
    assert "streamable-http" in result.output
