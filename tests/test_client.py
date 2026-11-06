"""HTTP client: headers, scoping, hosts, retries, dry-run, audit, downloads."""

from __future__ import annotations

import dataclasses
import io
import zipfile

import httpx
import pytest
import respx

from microsoft_ads_mcp.audit import AuditLog
from microsoft_ads_mcp.client import (
    CALL_RATE_WAIT,
    MicrosoftAdsAPIError,
    MicrosoftAdsClient,
    split_path,
)
from microsoft_ads_mcp.config import Config

from .conftest import ACCOUNT, CAMPAIGN, CUSTOMER, CUSTOMER_API, DEV_TOKEN, FakeAuth, audit_entries

QUERY = "/CampaignManagement/v13/Campaigns/QueryByIds"


@respx.mock
def test_headers_and_account_scope(client: MicrosoftAdsClient) -> None:
    route = respx.post(f"{CAMPAIGN}/Campaigns/QueryByIds").mock(
        return_value=httpx.Response(200, json={"Campaigns": []})
    )
    client.request("POST", QUERY, body={"AccountId": ACCOUNT}, read_only=True)
    h = route.calls.last.request.headers
    assert h["Authorization"] == "Bearer fake-access-token-abcdef"
    assert h["DeveloperToken"] == DEV_TOKEN
    assert h["CustomerId"] == CUSTOMER
    assert h["CustomerAccountId"] == ACCOUNT
    assert h["Content-Type"] == "application/json"
    assert h["User-Agent"].startswith("microsoft-ads-mcp/")


@respx.mock
def test_customer_management_is_unscoped(client: MicrosoftAdsClient) -> None:
    route = respx.post(f"{CUSTOMER_API}/User/Query").mock(
        return_value=httpx.Response(200, json={"User": {"Id": "5"}})
    )
    client.request(
        "POST", "/CustomerManagement/v13/User/Query", body={"UserId": None}, read_only=True
    )
    h = route.calls.last.request.headers
    assert "CustomerId" not in h and "CustomerAccountId" not in h
    assert h["DeveloperToken"] == DEV_TOKEN


@respx.mock
def test_parent_customer_is_looked_up_once(config: Config, audit: AuditLog) -> None:
    c = MicrosoftAdsClient(dataclasses.replace(config, customer_id=None), FakeAuth(), audit)
    lookup = respx.post(f"{CUSTOMER_API}/Account/Query").mock(
        return_value=httpx.Response(200, json={"Account": {"Id": "999", "ParentCustomerId": "777"}})
    )
    route = respx.post(f"{CAMPAIGN}/Campaigns/QueryByIds").mock(
        return_value=httpx.Response(200, json={"Campaigns": []})
    )
    c.request("POST", QUERY, body={}, account_id="999", read_only=True)
    c.request("POST", QUERY, body={}, account_id="999", read_only=True)
    assert lookup.call_count == 1
    assert route.calls.last.request.headers["CustomerId"] == "777"
    assert route.calls.last.request.headers["CustomerAccountId"] == "999"


def test_missing_account_is_explained(config: Config, audit: AuditLog) -> None:
    c = MicrosoftAdsClient(dataclasses.replace(config, account_id=None), FakeAuth(), audit)
    with pytest.raises(ValueError, match="microsoft_ads_list_accounts"):
        c.request("POST", QUERY, body={}, read_only=True)
    with pytest.raises(ValueError, match="numeric"):
        c.account("12ab")


@respx.mock
def test_sandbox_hosts(config: Config, audit: AuditLog) -> None:
    c = MicrosoftAdsClient(dataclasses.replace(config, environment="sandbox"), FakeAuth(), audit)
    route = respx.post(
        "https://campaign.api.sandbox.bingads.microsoft.com/CampaignManagement/v13/Campaigns/QueryByIds"
    ).mock(return_value=httpx.Response(200, json={}))
    c.request("POST", QUERY, body={}, read_only=True)
    assert route.called


@pytest.mark.parametrize(
    "path",
    [
        "CampaignManagement/v13/Campaigns",
        "https://evil.example.com/CampaignManagement/v13/Campaigns",
        "/CampaignManagement/v13/../../x",
        "/CampaignManagement/v12/Campaigns",
        "/Evil/v13/Campaigns",
        "/CampaignManagement/v13/Campaigns?x=1",
        "/CampaignManagement/v13/Campaigns%2F..",
        "/CampaignManagement/v13",
    ],
)
def test_bad_paths_are_rejected(path: str) -> None:
    with pytest.raises(ValueError):
        split_path(path)


@respx.mock
def test_retries_server_errors(client: MicrosoftAdsClient, _isolate: list[float]) -> None:
    route = respx.post(f"{CAMPAIGN}/Campaigns/QueryByIds").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json={"Campaigns": [{"Id": "1"}]})]
    )
    out = client.request("POST", QUERY, body={}, read_only=True)
    assert out["Campaigns"][0]["Id"] == "1"
    assert route.call_count == 2
    assert len(_isolate) == 1


@respx.mock
def test_call_rate_exceeded_waits_60_seconds(
    client: MicrosoftAdsClient, _isolate: list[float]
) -> None:
    fault = {
        "TrackingId": "t",
        "Errors": [{"Code": 117, "ErrorCode": "CallRateExceeded", "Message": "m"}],
    }
    respx.post(f"{CAMPAIGN}/Campaigns/QueryByIds").mock(
        side_effect=[httpx.Response(400, json=fault), httpx.Response(200, json={"Campaigns": []})]
    )
    client.request("POST", QUERY, body={}, read_only=True)
    assert _isolate == [CALL_RATE_WAIT]


@respx.mock
def test_401_refreshes_once(client: MicrosoftAdsClient, fake_auth: FakeAuth) -> None:
    respx.post(f"{CAMPAIGN}/Campaigns/QueryByIds").mock(
        side_effect=[httpx.Response(401), httpx.Response(200, json={})]
    )
    client.request("POST", QUERY, body={}, read_only=True)
    assert fake_auth.invalidated == 1


@respx.mock
def test_api_error_message_and_redaction(client: MicrosoftAdsClient) -> None:
    respx.post(f"{CAMPAIGN}/Campaigns/QueryByIds").mock(
        return_value=httpx.Response(
            400,
            json={
                "TrackingId": "track-1",
                "Type": "AdApiFaultDetail",
                "Errors": [
                    {"Code": 105, "ErrorCode": "InvalidCredentials", "Message": "bad Bearer x"}
                ],
            },
        )
    )
    with pytest.raises(MicrosoftAdsAPIError) as ei:
        client.request("POST", QUERY, body={}, read_only=True)
    msg = str(ei.value)
    assert "InvalidCredentials" in msg and "track-1" in msg
    assert "production vs sandbox" in msg
    assert "Bearer x" not in msg
    assert "105" in ei.value.codes


@respx.mock
def test_write_is_audited_with_before(client: MicrosoftAdsClient, tmp_audit_log) -> None:
    respx.put(f"{CAMPAIGN}/Campaigns").mock(
        return_value=httpx.Response(200, json={"PartialErrors": []})
    )
    out = client.request(
        "PUT",
        "/CampaignManagement/v13/Campaigns",
        body={"AccountId": ACCOUNT, "Campaigns": [{"Id": "1", "DailyBudget": 5}]},
        op="update_campaigns",
        before=[{"Id": "1", "DailyBudget": 4}],
    )
    assert out["audit_id"]
    [entry] = audit_entries(tmp_audit_log)
    assert entry["op"] == "update_campaigns"
    assert entry["before"] == [{"Id": "1", "DailyBudget": 4}]
    assert entry["customer_id"] == CUSTOMER and entry["account_id"] == ACCOUNT
    assert entry["response_status"] == 200


@respx.mock
def test_failed_write_is_audited(client: MicrosoftAdsClient, tmp_audit_log) -> None:
    respx.delete(f"{CAMPAIGN}/Campaigns").mock(
        return_value=httpx.Response(400, json={"Errors": []})
    )
    with pytest.raises(MicrosoftAdsAPIError):
        client.request("DELETE", "/CampaignManagement/v13/Campaigns", body={"CampaignIds": ["1"]})
    assert audit_entries(tmp_audit_log)[0]["error"] == "HTTP 400"


def test_dry_run_sends_nothing(config: Config, audit: AuditLog, tmp_audit_log) -> None:
    c = MicrosoftAdsClient(dataclasses.replace(config, dry_run=True), FakeAuth(), audit)
    with respx.mock(assert_all_called=False) as router:
        route = router.post(f"{CAMPAIGN}/Campaigns").mock(return_value=httpx.Response(200))
        out = c.request("POST", "/CampaignManagement/v13/Campaigns", body={"Campaigns": [{}]})
    assert out["_dry_run"] is True
    assert not route.called
    assert audit_entries(tmp_audit_log)[0]["dry_run"] is True


def test_reads_are_not_audited_in_dry_run(config: Config, audit: AuditLog, tmp_audit_log) -> None:
    c = MicrosoftAdsClient(dataclasses.replace(config, dry_run=True), FakeAuth(), audit)
    with respx.mock() as router:
        router.post(f"{CAMPAIGN}/Campaigns/QueryByIds").mock(
            return_value=httpx.Response(200, json={})
        )
        c.request("POST", QUERY, body={}, read_only=True)
    assert audit_entries(tmp_audit_log) == []


def _zip(name: str, text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(name, text)
    return buf.getvalue()


@respx.mock
def test_download_and_parse_zipped_csv(client: MicrosoftAdsClient) -> None:
    url = "https://example.blob.core.windows.net/reports/r.zip?sig=abc"
    respx.get(url).mock(
        return_value=httpx.Response(
            200, content=_zip("r.csv", '﻿"CampaignName","Clicks"\n"A","3"\n')
        )
    )
    rows = client.parse_csv_file(client.download(url))
    assert rows == [{"CampaignName": "A", "Clicks": "3"}]
    assert "Authorization" not in respx.calls.last.request.headers


def test_download_refuses_other_hosts(client: MicrosoftAdsClient) -> None:
    for url in ("https://evil.example.com/r.zip", "http://x.blob.core.windows.net/r.zip"):
        with pytest.raises(ValueError, match="non-Microsoft host"):
            client.download(url)


@respx.mock
def test_download_is_capped(config: Config, audit: AuditLog) -> None:
    c = MicrosoftAdsClient(dataclasses.replace(config, max_download_mb=1), FakeAuth(), audit)
    url = "https://download.api.bingads.microsoft.com/r.zip"
    respx.get(url).mock(return_value=httpx.Response(200, content=b"x" * (1024 * 1024 + 10)))
    with pytest.raises(ValueError, match="MICROSOFT_ADS_MAX_DOWNLOAD_MB"):
        c.download(url)
    bomb = _zip("big.csv", "a" * (2 * 1024 * 1024))
    with pytest.raises(ValueError, match="MICROSOFT_ADS_MAX_DOWNLOAD_MB"):
        c.parse_csv_file(bomb)
