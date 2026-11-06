"""Configuration, per-user folders and environment hosts."""

from __future__ import annotations

from pathlib import Path

import pytest

from microsoft_ads_mcp import config as cfg
from microsoft_ads_mcp.config import (
    SANDBOX_DEVELOPER_TOKEN,
    api_hosts,
    load_config,
    service_base_url,
)


def _base(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    monkeypatch.setenv("MICROSOFT_ADS_CLIENT_ID", "00001111-aaaa-2222-bbbb-3333cccc4444")
    monkeypatch.setenv("MICROSOFT_ADS_DEVELOPER_TOKEN", "FAKE-DEV")
    monkeypatch.setenv("MICROSOFT_ADS_REFRESH_TOKEN", "fake-refresh")
    for k, v in values.items():
        monkeypatch.setenv(k, v)


def test_client_id_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(RuntimeError, match="MICROSOFT_ADS_CLIENT_ID"):
        load_config()


def test_production_needs_developer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    _base(monkeypatch)
    monkeypatch.delenv("MICROSOFT_ADS_DEVELOPER_TOKEN")
    with pytest.raises(RuntimeError, match="DevSettings"):
        load_config()


def test_sandbox_uses_universal_token_and_sandbox_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    _base(monkeypatch, MICROSOFT_ADS_ENVIRONMENT="sandbox")
    monkeypatch.delenv("MICROSOFT_ADS_DEVELOPER_TOKEN")
    c = load_config()
    assert c.developer_token == SANDBOX_DEVELOPER_TOKEN
    assert c.base_url("CampaignManagement") == "https://campaign.api.sandbox.bingads.microsoft.com"
    assert c.token_url == "https://login.microsoftonline.com/common/oauth2/v2.0/token"


def test_hosts_per_service() -> None:
    assert service_base_url("CustomerManagement", "production") == (
        "https://clientcenter.api.bingads.microsoft.com"
    )
    assert (
        service_base_url("Reporting", "production") == "https://reporting.api.bingads.microsoft.com"
    )
    assert all(h.endswith(".bingads.microsoft.com") for h in api_hosts("sandbox"))
    with pytest.raises(ValueError):
        service_base_url("Evil", "production")


def test_bad_environment_and_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    _base(monkeypatch, MICROSOFT_ADS_ENVIRONMENT="staging")
    with pytest.raises(RuntimeError, match="production or sandbox"):
        load_config()
    _base(monkeypatch, MICROSOFT_ADS_ENVIRONMENT="production", MICROSOFT_ADS_ACCOUNT_ID="F1234")
    with pytest.raises(RuntimeError, match="numeric"):
        load_config()


def test_missing_refresh_token_explains(monkeypatch: pytest.MonkeyPatch) -> None:
    _base(monkeypatch)
    monkeypatch.delenv("MICROSOFT_ADS_REFRESH_TOKEN")
    with pytest.raises(RuntimeError, match="microsoft-ads-mcp auth"):
        load_config()
    assert load_config(require_refresh_token=False).refresh_token is None


def test_default_paths_are_per_user(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _base(monkeypatch)
    c = load_config()
    home = tmp_path / "home"
    assert c.token_file == home / "secrets" / "microsoft-ads-token.json"
    assert c.audit_log == home / "logs" / "audit.jsonl"
    assert c.refresh_token_from_env is True
    monkeypatch.delenv("MICROSOFT_ADS_HOME")
    assert cfg.app_home() == Path.home() / ".microsoft-ads-mcp"


def test_token_file_is_read(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _base(monkeypatch)
    monkeypatch.delenv("MICROSOFT_ADS_REFRESH_TOKEN")
    token = tmp_path / "home" / "secrets" / "microsoft-ads-token.json"
    token.parent.mkdir(parents=True)
    token.write_text('{"refresh_token": "from-file"}')
    c = load_config()
    assert c.refresh_token == "from-file"
    assert c.refresh_token_from_env is False


def test_home_env_file_is_read(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".env").write_text(
        "MICROSOFT_ADS_CLIENT_ID=00001111-aaaa-2222-bbbb-3333cccc4444\n"
        "MICROSOFT_ADS_ENVIRONMENT=sandbox\nMICROSOFT_ADS_REFRESH_TOKEN=r\n"
        "MICROSOFT_ADS_ACCOUNT_ID=42\n"
    )
    (tmp_path / ".env").write_text("MICROSOFT_ADS_ACCOUNT_ID=7\n")
    c = load_config()
    assert c.environment == "sandbox"
    assert c.account_id == "7"  # ./.env wins over the home .env


def test_limits_and_groups(monkeypatch: pytest.MonkeyPatch) -> None:
    _base(
        monkeypatch,
        MICROSOFT_ADS_MAX_INCREASE_PCT="15",
        MICROSOFT_ADS_MAX_DAILY_BUDGET="100",
        MICROSOFT_ADS_TOOL_GROUPS="Reporting, ad-groups",
        MICROSOFT_ADS_ALLOW_REMOTE="true",
    )
    c = load_config()
    assert c.max_increase_pct == 15
    assert c.max_daily_budget == 100
    assert c.tool_groups == ["ad_groups", "reporting"]
    assert c.allow_remote is True
    assert load_config().max_download_mb == 200
