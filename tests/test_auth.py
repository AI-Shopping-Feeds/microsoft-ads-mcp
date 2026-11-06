"""Token refresh, caching, rotation, PKCE and redaction."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from microsoft_ads_mcp import auth as auth_mod
from microsoft_ads_mcp.auth import (
    MicrosoftAuth,
    OAuthError,
    exchange_code,
    pkce_pair,
    redact,
    save_token_file,
)

TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"


def _auth(token_file: Path | None = None, secret: str | None = None) -> MicrosoftAuth:
    return MicrosoftAuth(
        client_id="00001111-aaaa-2222-bbbb-3333cccc4444",
        client_secret=secret,
        refresh_token="fake-refresh-one",
        token_url=TOKEN_URL,
        token_file=token_file,
    )


def _form(route: respx.Route) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(route.calls.last.request.content.decode()).items()}


@respx.mock
def test_refresh_sends_scope_and_caches() -> None:
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "access-1", "expires_in": 3600})
    )
    a = _auth()
    assert a.access_token() == "access-1"
    assert a.access_token() == "access-1"
    assert route.call_count == 1
    form = _form(route)
    assert form["grant_type"] == "refresh_token"
    assert form["refresh_token"] == "fake-refresh-one"
    assert form["scope"] == "https://ads.microsoft.com/msads.manage offline_access"
    assert "client_secret" not in form


@respx.mock
def test_client_secret_is_sent_for_web_apps() -> None:
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "a", "expires_in": 3600})
    )
    _auth(secret="web-app-secret-value").access_token()
    assert _form(route)["client_secret"] == "web-app-secret-value"


@respx.mock
def test_expired_token_is_refreshed(monkeypatch: pytest.MonkeyPatch) -> None:
    route = respx.post(TOKEN_URL).mock(
        side_effect=[
            httpx.Response(200, json={"access_token": "first", "expires_in": 3600}),
            httpx.Response(200, json={"access_token": "second", "expires_in": 3600}),
        ]
    )
    now = [1_000_000.0]
    monkeypatch.setattr(auth_mod.time, "time", lambda: now[0])
    a = _auth()
    assert a.access_token() == "first"
    now[0] += 3600 - 60  # inside the safety margin before expiry
    assert a.access_token() == "second"
    assert route.call_count == 2


@respx.mock
def test_invalidate_forces_refresh() -> None:
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "x", "expires_in": 3600})
    )
    a = _auth()
    a.access_token()
    a.invalidate()
    a.access_token()
    assert route.call_count == 2


@respx.mock
def test_refusal_is_redacted() -> None:
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            400,
            json={
                "error": "invalid_grant",
                "error_description": "AADSTS70000: bad grant fake-refresh-one\r\nTrace ID: x",
            },
        )
    )
    with pytest.raises(OAuthError) as ei:
        _auth().access_token()
    msg = str(ei.value)
    assert "invalid_grant" in msg
    assert "fake-refresh-one" not in msg
    assert "Trace ID" not in msg
    assert "microsoft-ads-mcp auth" in msg


@respx.mock
def test_rotated_refresh_token_is_saved_to_its_file(tmp_path: Path) -> None:
    token_file = tmp_path / "secrets" / "token.json"
    save_token_file(token_file, {"refresh_token": "fake-refresh-one", "environment": "production"})
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={"access_token": "a", "expires_in": 3600, "refresh_token": "fake-refresh-two"},
        )
    )
    _auth(token_file).access_token()
    data = json.loads(token_file.read_text())
    assert data == {"refresh_token": "fake-refresh-two", "environment": "production"}


@respx.mock
def test_rotation_without_file_stays_in_memory(tmp_path: Path) -> None:
    route = respx.post(TOKEN_URL).mock(
        side_effect=[
            httpx.Response(200, json={"access_token": "a", "expires_in": 0, "refresh_token": "r2"}),
            httpx.Response(200, json={"access_token": "b", "expires_in": 3600}),
        ]
    )
    a = _auth(None)
    a.access_token()
    a.access_token()
    assert _form(route)["refresh_token"] == "r2"
    assert not list(tmp_path.iterdir())


def test_token_file_and_folder_are_owner_only(tmp_path: Path) -> None:
    path = tmp_path / "secrets" / "token.json"
    save_token_file(path, {"refresh_token": "abc"})
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert not (tmp_path / "secrets" / "token.json.tmp").exists()


def test_pkce_pair_is_s256() -> None:
    verifier, challenge = pkce_pair()
    assert 43 <= len(verifier) <= 128
    digest = hashlib.sha256(verifier.encode()).digest()
    assert challenge == base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


@respx.mock
def test_exchange_code_sends_verifier_and_redirect() -> None:
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "a", "refresh_token": "r"})
    )
    out = exchange_code(
        code="THECODE",
        redirect_uri="http://localhost:8765/callback",
        client_id="cid",
        token_url=TOKEN_URL,
        code_verifier="verifier-value",
    )
    assert out["refresh_token"] == "r"
    form = _form(route)
    assert form["grant_type"] == "authorization_code"
    assert form["code_verifier"] == "verifier-value"
    assert form["redirect_uri"] == "http://localhost:8765/callback"


@respx.mock
def test_exchange_code_refusal_mentions_redirect() -> None:
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant", "error_description": "x"})
    )
    with pytest.raises(OAuthError, match="redirect URI"):
        exchange_code(
            code="c", redirect_uri="r", client_id="cid", token_url=TOKEN_URL, code_verifier="v"
        )


def test_redact_hides_tokens_and_secret_keys() -> None:
    auth_mod.register_secret("my-very-secret-client-secret")
    jwt = "eyJ0eXAiOiJKV1QiLCJhbGciOi.eyJhdWQiOiJodHRwczovL2Fkcy5t.c2lnbmF0dXJl"
    out = redact(
        {
            "message": f"token {jwt} and my-very-secret-client-secret",
            "refresh_token": "anything",
            "DeveloperToken": "FAKE-DEV",
            "nested": [{"Authorization": "Bearer abc"}],
            "Code": 117,
        }
    )
    assert out["message"] == "token *** and ***"
    assert out["refresh_token"] == "***"
    assert out["DeveloperToken"] == "***"
    assert out["nested"][0]["Authorization"] == "***"
    assert out["Code"] == 117
    assert redact("header Bearer abc.def") == "header ***"
