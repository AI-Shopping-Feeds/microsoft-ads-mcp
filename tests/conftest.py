"""Shared fixtures for the test suite.

All tests run fully offline: HTTP is mocked with respx and no real Microsoft
credentials are used. Every value here is an obviously fake placeholder.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest
from mcp import Client

from microsoft_ads_mcp import server
from microsoft_ads_mcp.audit import AuditLog
from microsoft_ads_mcp.client import MicrosoftAdsClient
from microsoft_ads_mcp.config import Config

CUSTOMER = "1111111"
ACCOUNT = "2222222"
CLIENT_ID = "00001111-aaaa-2222-bbbb-3333cccc4444"
CAMPAIGN = "https://campaign.api.bingads.microsoft.com/CampaignManagement/v13"
CUSTOMER_API = "https://clientcenter.api.bingads.microsoft.com/CustomerManagement/v13"
REPORTING = "https://reporting.api.bingads.microsoft.com/Reporting/v13"
ADINSIGHT = "https://adinsight.api.bingads.microsoft.com/AdInsight/v13"
BULK = "https://bulk.api.bingads.microsoft.com/Bulk/v13"
DEV_TOKEN = "FAKE-DEV-TOKEN-0000"


class FakeAuth:
    """Stand-in for MicrosoftAuth in tests."""

    account_label = "fake:test"

    def __init__(self) -> None:
        self.invalidated = 0
        self.token = "fake-access-token-abcdef"

    def access_token(self) -> str:
        return self.token

    def invalidate(self) -> None:
        self.invalidated += 1


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[float]:
    """No real sleeping, no real home folder, no stray MICROSOFT_ADS_* settings."""
    slept: list[float] = []
    monkeypatch.setattr("microsoft_ads_mcp.client.time.sleep", lambda s: slept.append(s))
    import os

    for var in list(os.environ):
        if var.startswith("MICROSOFT_ADS_"):
            monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("MICROSOFT_ADS_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    return slept


@pytest.fixture
def tmp_audit_log(tmp_path: Path) -> Path:
    return tmp_path / "logs" / "audit.jsonl"


@pytest.fixture
def config(tmp_audit_log: Path, tmp_path: Path) -> Config:
    return Config(
        client_id=CLIENT_ID,
        developer_token=DEV_TOKEN,
        refresh_token="fake-refresh-token-value",
        audit_log=tmp_audit_log,
        customer_id=CUSTOMER,
        account_id=ACCOUNT,
        token_file=tmp_path / "secrets" / "token.json",
        timeout=5.0,
    )


@pytest.fixture
def audit(tmp_audit_log: Path) -> AuditLog:
    return AuditLog(tmp_audit_log)


@pytest.fixture
def fake_auth() -> FakeAuth:
    return FakeAuth()


@pytest.fixture
def client(config: Config, audit: AuditLog, fake_auth: FakeAuth):
    c = MicrosoftAdsClient(config, fake_auth, audit)
    yield c
    c.close()


@pytest.fixture
def patch_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "load_auth", lambda config: FakeAuth())


def audit_entries(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def payload(result: Any) -> Any:
    assert not result.is_error, result.content
    return result.structured_content or json.loads(result.content[0].text)


def error_text(result: Any) -> str:
    assert result.is_error
    return " ".join(getattr(block, "text", "") for block in result.content)


async def call(config: Config, tool: str, args: dict[str, Any], **changes: Any) -> Any:
    mcp = server.build_server(dataclasses.replace(config, **changes))
    async with Client(mcp) as c:
        return await c.call_tool(tool, args)


def body_of(route: Any, index: int = -1) -> Any:
    return json.loads(route.calls[index].request.content)
