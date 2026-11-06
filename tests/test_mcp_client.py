"""End-to-end tests through `mcp.Client` against the real server (fake auth, mocked HTTP)."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from mcp import Client
from mcp.server.mcpserver import MCPServer
from mcp.types import Tool

from microsoft_ads_mcp import __version__, server, tools
from microsoft_ads_mcp.client import MicrosoftAdsClient
from microsoft_ads_mcp.config import Config, load_config
from microsoft_ads_mcp.tool_catalog import ALWAYS_REGISTERED, TOOL_SPECS

from .conftest import ACCOUNT, CAMPAIGN, CUSTOMER_API, error_text, payload

pytestmark = pytest.mark.usefixtures("patch_auth")

META_TOOLS = [
    "microsoft_ads_describe_server",
    "microsoft_ads_health_check",
    "microsoft_ads_audit_lookup",
    "microsoft_ads_audit_tail",
    "microsoft_ads_set_dry_run",
]
EXPECTED_TOOL_COUNT = 70


def _build(config: Config, **changes: Any) -> MCPServer:
    return server.build_server(dataclasses.replace(config, **changes))


async def _tools(mcp: MCPServer) -> list[Tool]:
    async with Client(mcp) as c:
        return (await c.list_tools()).tools


def _group_tool_names(client: MicrosoftAdsClient) -> dict[str, list[str]]:
    """Tool names per group, by registering each module on its own server."""
    out: dict[str, list[str]] = {}
    for group in tools.TOOL_GROUPS:
        mcp = MCPServer("probe")
        getattr(tools, group).register(mcp, client)
        out[group] = list(mcp._tool_manager._tools)
    return out


async def test_server_reports_version_and_instructions(config: Config) -> None:
    async with Client(_build(config)) as c:
        assert c.server_info is not None
        assert c.server_info.name == "microsoft-ads-mcp"
        assert c.server_info.version == __version__
        assert c.instructions
        assert "microsoft_ads_describe_server" in c.instructions
        assert "dry-run" in c.instructions
        assert "MICROSOFT_ADS_TOOL_GROUPS" in c.instructions
        assert "authorised" in c.instructions
        assert 4 <= len(c.instructions.splitlines()) <= 8


async def test_every_tool_has_a_catalog_entry(config: Config) -> None:
    listed = await _tools(_build(config))
    assert len(listed) == EXPECTED_TOOL_COUNT
    for tool in listed:
        assert tool.name.startswith("microsoft_ads_"), tool.name
        assert tool.name in TOOL_SPECS, f"{tool.name} has no tool_catalog entry"
        assert tool.title and tool.title[0].isupper(), tool.name
        assert tool.description, tool.name
        a = tool.annotations
        assert a is not None, tool.name
        assert a.read_only_hint is not None and a.destructive_hint is not None
        assert a.idempotent_hint is not None and a.open_world_hint is not None
    assert {t.name for t in listed} == set(TOOL_SPECS)


async def test_annotations_are_plausible(config: Config) -> None:
    by_name = {t.name: t.annotations for t in await _tools(_build(config))}
    read_only = {n for n, a in by_name.items() if a and a.read_only_hint}
    destructive = {n for n, a in by_name.items() if a and a.destructive_hint}
    assert not read_only & destructive
    for name in by_name:
        verb = name.removeprefix("microsoft_ads_").split("_")[0]
        if verb in {"list", "get", "poll", "download", "describe", "audit"}:
            assert name in read_only, name
        if verb == "delete":
            assert name in destructive, name
        if verb in {"create", "update", "add", "set", "adjust", "apply", "dismiss"} and name != (
            "microsoft_ads_set_dry_run"
        ):
            assert name not in read_only, name
    assert "microsoft_ads_request" in destructive
    assert {
        "microsoft_ads_run_report",
        "microsoft_ads_read_request",
        "microsoft_ads_bulk_download",
    } <= read_only
    closed = {n for n, a in by_name.items() if a and a.open_world_hint is False}
    assert closed == set(META_TOOLS) - {"microsoft_ads_health_check"}


async def test_tools_list_order_is_deterministic(
    config: Config, client: MicrosoftAdsClient
) -> None:
    first = [t.name for t in await _tools(_build(config))]
    assert first == [t.name for t in await _tools(_build(config))]
    per_group = _group_tool_names(client)
    assert first == META_TOOLS + [n for g in tools.TOOL_GROUPS for n in per_group[g]]


async def test_tool_groups_limit_registration(config: Config, client: MicrosoftAdsClient) -> None:
    names = [t.name for t in await _tools(_build(config, tool_groups=["reporting", "accounts"]))]
    per_group = _group_tool_names(client)
    assert names == META_TOOLS + per_group["accounts"] + per_group["reporting"]


async def test_read_only_registers_only_read_tools(config: Config) -> None:
    listed = await _tools(_build(config, read_only=True))
    names = {t.name for t in listed}
    for tool in listed:
        if tool.name not in ALWAYS_REGISTERED:
            assert tool.annotations and tool.annotations.read_only_hint, tool.name
    assert "microsoft_ads_update_campaigns" not in names
    assert "microsoft_ads_request" not in names
    assert {"microsoft_ads_list_campaigns", "microsoft_ads_run_report"} <= names
    expected = {n for n, s in TOOL_SPECS.items() if s.annotations.read_only_hint}
    assert names == expected | set(META_TOOLS)


async def test_read_only_combines_with_groups(config: Config) -> None:
    names = {
        t.name for t in await _tools(_build(config, tool_groups=["bulk_edits"], read_only=True))
    }
    assert names == set(META_TOOLS)


def _env(monkeypatch: pytest.MonkeyPatch, **values: str) -> Path:
    monkeypatch.setenv("MICROSOFT_ADS_CLIENT_ID", "00001111-aaaa-2222-bbbb-3333cccc4444")
    monkeypatch.setenv("MICROSOFT_ADS_ENVIRONMENT", "sandbox")
    monkeypatch.setenv("MICROSOFT_ADS_REFRESH_TOKEN", "fake-refresh")
    for k, v in values.items():
        monkeypatch.setenv(k, v)
    return Path("missing.env")


async def test_env_vars_filter_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = _env(
        monkeypatch, MICROSOFT_ADS_TOOL_GROUPS="accounts,labels", MICROSOFT_ADS_READ_ONLY="1"
    )
    names = {t.name for t in await _tools(server.build_server(env_file=env_file))}
    assert names == set(META_TOOLS) | {
        "microsoft_ads_get_user",
        "microsoft_ads_list_accounts",
        "microsoft_ads_get_account",
        "microsoft_ads_list_customers",
        "microsoft_ads_list_labels",
        "microsoft_ads_list_label_associations",
    }


def test_unknown_group_fails_at_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = _env(monkeypatch, MICROSOFT_ADS_TOOL_GROUPS="accounts,nope")
    with pytest.raises(RuntimeError) as exc_info:
        server.build_server(env_file=env_file)
    message = str(exc_info.value)
    assert "nope" in message
    for group in tools.TOOL_GROUPS:
        assert group in message


def test_load_config_normalises_group_names(monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = _env(monkeypatch, MICROSOFT_ADS_TOOL_GROUPS="Reporting, asset-groups")
    assert load_config(env_file=env_file).tool_groups == ["asset_groups", "reporting"]


@respx.mock
async def test_api_error_reaches_the_client(config: Config) -> None:
    respx.post(f"{CAMPAIGN}/Campaigns/QueryByAccountId").mock(
        return_value=httpx.Response(
            403,
            json={
                "TrackingId": "t9",
                "Errors": [{"Code": 106, "ErrorCode": "UserIsNotAuthorized", "Message": "m"}],
            },
        )
    )
    async with Client(_build(config)) as c:
        result = await c.call_tool("microsoft_ads_list_campaigns", {})
    text = error_text(result)
    assert "Microsoft Advertising API error 403" in text
    assert "UserIsNotAuthorized" in text and "t9" in text


async def test_describe_server_reports_settings(config: Config) -> None:
    async with Client(_build(config, tool_groups=["reporting"], read_only=True)) as c:
        result = await c.call_tool("microsoft_ads_describe_server", {})
    p = payload(result)
    assert p["tool_groups"] == ["reporting"] and p["read_only"] is True
    assert p["environment"] == "production" and p["version"] == __version__
    assert p["default_account_id"] == ACCOUNT
    assert "FAKE-DEV" not in json.dumps(p)
    assert all(h.endswith(".bingads.microsoft.com") for h in p["api_hosts"])


@respx.mock
async def test_health_check_lists_accounts(config: Config) -> None:
    respx.post(f"{CUSTOMER_API}/User/Query").mock(
        return_value=httpx.Response(
            200, json={"User": {"Id": "55", "UserName": "u"}, "CustomerRoles": []}
        )
    )
    search = respx.post(f"{CUSTOMER_API}/Accounts/Search").mock(
        return_value=httpx.Response(
            200,
            json={"Accounts": [{"Id": ACCOUNT, "Name": "Example Shop", "ParentCustomerId": "1"}]},
        )
    )
    async with Client(_build(config)) as c:
        result = await c.call_tool("microsoft_ads_health_check", {})
    p = payload(result)
    assert p["ok"] is True
    assert [ch["check"] for ch in p["checks"]] == [
        "token_refresh",
        "get_user",
        "list_accounts",
        "default_account_visible",
    ]
    assert p["accounts"][0]["Name"] == "Example Shop"
    assert json.loads(search.calls.last.request.content)["Predicates"][0] == {
        "Field": "UserId",
        "Operator": "Equals",
        "Value": "55",
    }


async def test_set_dry_run_and_audit_tail(config: Config) -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.post(f"{CAMPAIGN}/Campaigns").mock(return_value=httpx.Response(200, json={}))
        async with Client(_build(config)) as c:
            await c.call_tool("microsoft_ads_set_dry_run", {"enabled": True})
            created = await c.call_tool(
                "microsoft_ads_create_campaigns", {"items": [{"Name": "x", "DailyBudget": 5}]}
            )
            tail = await c.call_tool("microsoft_ads_audit_tail", {"limit": 5})
            audit_id = payload(created)["audit_id"]
            found = await c.call_tool("microsoft_ads_audit_lookup", {"audit_id": audit_id})
    assert payload(created)["_dry_run"] is True
    assert not route.called
    assert payload(tail)["count"] == 1
    assert payload(found)["found"] is True


def test_version_matches_pyproject() -> None:
    root = Path(__file__).resolve().parent.parent
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert f'\nversion = "{__version__}"\n' in pyproject


def test_docs_list_every_tool() -> None:
    root = Path(__file__).resolve().parent.parent
    docs = (root / "docs" / "tools.md").read_text(encoding="utf-8")
    missing = [name for name in TOOL_SPECS if f"`{name}`" not in docs]
    assert not missing, f"docs/tools.md is missing {missing}"
    assert f"**{len(TOOL_SPECS)} tools" in docs
