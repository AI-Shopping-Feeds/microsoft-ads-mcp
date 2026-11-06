"""Microsoft identity platform (Entra ID) OAuth tokens for Microsoft Advertising.

`MicrosoftAuth` swaps a long-lived refresh token for short-lived access tokens
and caches each one until shortly before it expires. Microsoft usually returns
a new refresh token with every refresh; it replaces the old one in memory and,
when the token came from `microsoft-ads-mcp auth`, in the owner-only token file.

Secrets are never logged: use `redact()` on anything that might contain one.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Protocol

import httpx

from .config import SCOPE, Config, ensure_private_dir

# Refresh this many seconds before the access token's stated expiry.
EXPIRY_MARGIN = 120

# JWT-shaped access tokens and the Bearer header.
_TOKEN_RE = re.compile(
    r"(eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]*|Bearer\s+\S+)"
)
_SECRET_KEYS = {
    "access_token",
    "refresh_token",
    "id_token",
    "client_secret",
    "code_verifier",
    "authorization",
    "developertoken",
    "developer_token",
    "password",
}
_extra_secrets: set[str] = set()


def register_secret(value: str | None) -> None:
    """Remember a secret value (client secret, tokens) so redact() hides it."""
    if value and len(value) >= 8:
        _extra_secrets.add(value)


def redact(value: Any) -> Any:
    """Return a copy of value with tokens and known secrets replaced by '***'."""
    if isinstance(value, str):
        out = _TOKEN_RE.sub("***", value)
        for secret in _extra_secrets:
            out = out.replace(secret, "***")
        return out
    if isinstance(value, dict):
        return {
            k: ("***" if str(k).lower() in _SECRET_KEYS and v else redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [redact(v) for v in value]
    return value


class Auth(Protocol):
    @property
    def account_label(self) -> str: ...

    def access_token(self) -> str: ...

    def invalidate(self) -> None: ...


class OAuthError(RuntimeError):
    """The token endpoint refused the request (bad client, revoked or expired token)."""


def _safe_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return {"_raw": resp.text[:500]}


def _token_error(payload: Any) -> str:
    if isinstance(payload, dict):
        err = payload.get("error", "")
        desc = str(payload.get("error_description", "")).split("\r\n")[0]
        return f"{err}: {desc}".strip(": ")
    return str(payload)[:300]


class MicrosoftAuth:
    """Thread-safe refresh-token holder that caches access tokens until expiry."""

    def __init__(
        self,
        *,
        client_id: str,
        refresh_token: str,
        token_url: str,
        client_secret: str | None = None,
        token_file: Path | None = None,
        timeout: float = 30.0,
    ):
        self.client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self.token_url = token_url
        self.token_file = token_file
        self._timeout = timeout
        self._lock = threading.Lock()
        self._token: str | None = None
        self._expires_at = 0.0
        register_secret(client_secret)
        register_secret(refresh_token)

    @property
    def account_label(self) -> str:
        return f"entra:{self.client_id[-6:]}"

    @property
    def expires_in(self) -> int:
        return max(0, int(self._expires_at - time.time()))

    def invalidate(self) -> None:
        with self._lock:
            self._token = None
            self._expires_at = 0.0

    def access_token(self) -> str:
        with self._lock:
            if self._token and time.time() < self._expires_at - EXPIRY_MARGIN:
                return self._token
            data = {
                "client_id": self.client_id,
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
                "scope": SCOPE,
            }
            if self._client_secret:
                data["client_secret"] = self._client_secret
            try:
                resp = httpx.post(self.token_url, data=data, timeout=self._timeout)
            except httpx.HTTPError as e:
                raise OAuthError(
                    f"Could not reach the Microsoft identity platform: {redact(str(e))}"
                ) from e
            payload = _safe_json(resp)
            if resp.status_code != 200:
                raise OAuthError(
                    f"Microsoft refused the token refresh (HTTP {resp.status_code}): "
                    f"{redact(_token_error(payload))}. If the refresh token was revoked or "
                    "has expired (for example after a password change), run "
                    "`microsoft-ads-mcp auth` again."
                )
            token = payload.get("access_token") if isinstance(payload, dict) else None
            if not token:
                raise OAuthError("The Microsoft identity platform returned no access token.")
            self._token = token
            register_secret(token)
            self._expires_at = time.time() + float(payload.get("expires_in", 3600))
            new_refresh = payload.get("refresh_token")
            if new_refresh and new_refresh != self._refresh_token:
                self._refresh_token = new_refresh
                register_secret(new_refresh)
                if self.token_file is not None and self.token_file.exists():
                    save_token_file(self.token_file, {"refresh_token": new_refresh})
            return token


def save_token_file(path: Path, data: dict[str, Any]) -> None:
    """Write (or merge into) the token file: folder 0700, file 0600."""
    ensure_private_dir(path.parent)
    existing: dict[str, Any] = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            existing = {}
    existing.update(data)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2)
    os.replace(tmp, path)
    if os.name == "posix":
        os.chmod(path, 0o600)


def pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, S256 code_challenge) for the authorization code flow."""
    verifier = secrets.token_urlsafe(64)[:96]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def exchange_code(
    *,
    code: str,
    redirect_uri: str,
    client_id: str,
    token_url: str,
    code_verifier: str,
    client_secret: str | None = None,
) -> dict[str, Any]:
    """Swap a one-time authorization code for access and refresh tokens."""
    data = {
        "client_id": client_id,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "scope": SCOPE,
        "code_verifier": code_verifier,
    }
    if client_secret:
        data["client_secret"] = client_secret
    resp = httpx.post(token_url, data=data, timeout=30.0)
    payload = _safe_json(resp)
    if resp.status_code != 200 or not isinstance(payload, dict) or "refresh_token" not in payload:
        raise OAuthError(
            f"Microsoft refused the authorization code (HTTP {resp.status_code}): "
            f"{redact(_token_error(payload))}. Codes expire after about five minutes; "
            "run the command again. Check that the redirect URI is registered on the app."
        )
    return payload


def load_auth(config: Config) -> MicrosoftAuth:
    if not config.refresh_token:
        raise RuntimeError("No refresh token configured. Run `microsoft-ads-mcp auth` first.")
    return MicrosoftAuth(
        client_id=config.client_id,
        client_secret=config.client_secret,
        refresh_token=config.refresh_token,
        token_url=config.token_url,
        # Rotated refresh tokens are saved back only to the file they came from.
        token_file=None if config.refresh_token_from_env else config.token_file,
        timeout=config.timeout,
    )
