"""Report, change-history and bulk-download flows (in memory, with progress)."""

from __future__ import annotations

import io
import zipfile
from typing import Any

import httpx
import pytest
import respx
from mcp import Client

from microsoft_ads_mcp import server
from microsoft_ads_mcp.config import Config

from .conftest import ACCOUNT, BULK, REPORTING, body_of, call, error_text, payload

pytestmark = pytest.mark.usefixtures("patch_auth")
URL = "https://reportdownload.blob.core.windows.net/r/report.zip?sig=x"


def _zip(text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("report.csv", text)
    return buf.getvalue()


@respx.mock
async def test_run_report_submits_polls_and_downloads(config: Config, tmp_path) -> None:
    submit = respx.post(f"{REPORTING}/GenerateReport/Submit").mock(
        return_value=httpx.Response(200, json={"ReportRequestId": "rr1"})
    )
    respx.post(f"{REPORTING}/GenerateReport/Poll").mock(
        side_effect=[
            httpx.Response(200, json={"ReportRequestStatus": {"Status": "Pending"}}),
            httpx.Response(
                200, json={"ReportRequestStatus": {"Status": "Success", "ReportDownloadUrl": URL}}
            ),
        ]
    )
    respx.get(URL).mock(
        return_value=httpx.Response(
            200, content=_zip('"CampaignName","Clicks"\n"A","1"\n"B","2"\n')
        )
    )
    progress: list[Any] = []

    async def on_progress(done: float, total: float | None, message: str | None) -> None:
        progress.append(message)

    mcp = server.build_server(config)
    async with Client(mcp) as c:
        result = await c.call_tool(
            "microsoft_ads_run_report",
            {
                "report_type": "CampaignPerformance",
                "columns": ["CampaignName", "Clicks"],
                "start_date": "2026-10-01",
                "end_date": "2026-10-31",
                "max_rows": 1,
                "poll_seconds": 0,
            },
            progress_callback=on_progress,
        )
    out = payload(result)
    assert out["row_count"] == 2 and out["rows"] == [{"CampaignName": "A", "Clicks": "1"}]
    assert out["truncated"] is True
    req = body_of(submit)["ReportRequest"]
    assert req["Type"] == "CampaignPerformanceReportRequest"
    assert req["Scope"] == {"AccountIds": [ACCOUNT]}
    assert req["Time"]["CustomDateRangeStart"] == {"Year": 2026, "Month": 10, "Day": 1}
    assert req["ExcludeReportHeader"] is True and req["Aggregation"] == "Summary"
    assert any("Submitted" in (m or "") for m in progress)
    assert not list(tmp_path.glob("**/*.csv"))


@respx.mock
async def test_success_without_url_means_no_data(config: Config) -> None:
    respx.post(f"{REPORTING}/GenerateReport/Poll").mock(
        return_value=httpx.Response(200, json={"ReportRequestStatus": {"Status": "Success"}})
    )
    out = payload(await call(config, "microsoft_ads_download_report", {"report_request_id": "rr1"}))
    assert out["row_count"] == 0 and "no data" in out["message"]
    polled = payload(await call(config, "microsoft_ads_poll_report", {"report_request_id": "rr1"}))
    assert polled == {"report_request_id": "rr1", "status": "Success", "has_data": False}


@respx.mock
async def test_failed_report(config: Config) -> None:
    respx.post(f"{REPORTING}/GenerateReport/Submit").mock(
        return_value=httpx.Response(200, json={"ReportRequestId": "rr2"})
    )
    respx.post(f"{REPORTING}/GenerateReport/Poll").mock(
        return_value=httpx.Response(200, json={"ReportRequestStatus": {"Status": "Error"}})
    )
    out = payload(
        await call(
            config,
            "microsoft_ads_run_report",
            {
                "report_type": "AccountPerformanceReportRequest",
                "columns": ["Clicks"],
                "predefined_time": "LastSevenDays",
            },
        )
    )
    assert out["status"] == "Error"


async def test_report_argument_checks(config: Config) -> None:
    bad_date = await call(
        config,
        "microsoft_ads_submit_report",
        {
            "report_type": "CampaignPerformance",
            "columns": ["Clicks"],
            "start_date": "1/1/2026",
            "end_date": "2026-01-02",
        },
    )
    assert "YYYY-MM-DD" in error_text(bad_date)
    both = await call(
        config,
        "microsoft_ads_submit_report",
        {
            "report_type": "CampaignPerformance",
            "columns": ["Clicks"],
            "predefined_time": "Today",
            "start_date": "2026-01-01",
            "end_date": "2026-01-02",
        },
    )
    assert "not both" in error_text(both)
    agg = await call(
        config,
        "microsoft_ads_submit_report",
        {
            "report_type": "CampaignPerformance",
            "columns": ["Clicks"],
            "predefined_time": "Today",
            "aggregation": "Fortnightly",
        },
    )
    assert "aggregation" in error_text(agg)


@respx.mock
async def test_change_history_defaults(config: Config) -> None:
    submit = respx.post(f"{REPORTING}/GenerateReport/Submit").mock(
        return_value=httpx.Response(200, json={"ReportRequestId": "rr3"})
    )
    respx.post(f"{REPORTING}/GenerateReport/Poll").mock(
        return_value=httpx.Response(
            200, json={"ReportRequestStatus": {"Status": "Success", "ReportDownloadUrl": URL}}
        )
    )
    respx.get(URL).mock(
        return_value=httpx.Response(200, content=_zip('"DateTime","ChangedBy"\n"x","y"\n'))
    )
    out = payload(await call(config, "microsoft_ads_change_history", {}))
    assert out["rows"] == [{"DateTime": "x", "ChangedBy": "y"}]
    req = body_of(submit)["ReportRequest"]
    assert req["Type"] == "SearchCampaignChangeHistoryReportRequest"
    assert "Aggregation" not in req
    assert req["Time"] == {"PredefinedTime": "LastSevenDays"}


async def test_report_tools_work_in_read_only_and_dry_run(config: Config) -> None:
    with respx.mock() as router:
        router.post(f"{REPORTING}/GenerateReport/Submit").mock(
            return_value=httpx.Response(200, json={"ReportRequestId": "rr4"})
        )
        out = payload(
            await call(
                config,
                "microsoft_ads_submit_report",
                {
                    "report_type": "CampaignPerformance",
                    "columns": ["Clicks"],
                    "predefined_time": "Yesterday",
                },
                read_only=True,
                dry_run=True,
            )
        )
    assert out["report_request_id"] == "rr4"


@respx.mock
async def test_bulk_download(config: Config) -> None:
    req = respx.post(f"{BULK}/Campaigns/DownloadByAccountIds").mock(
        return_value=httpx.Response(200, json={"DownloadRequestId": "d1"})
    )
    respx.post(f"{BULK}/BulkDownloadStatus/Query").mock(
        side_effect=[
            httpx.Response(200, json={"RequestStatus": "InProgress", "PercentComplete": 50}),
            httpx.Response(200, json={"RequestStatus": "Completed", "ResultFileUrl": URL}),
        ]
    )
    respx.get(URL).mock(
        return_value=httpx.Response(200, content=_zip("Type,Id,Name\nCampaign,1,Brand\n"))
    )
    out = payload(await call(config, "microsoft_ads_bulk_download", {"poll_seconds": 0}))
    assert out["rows"] == [{"Type": "Campaign", "Id": "1", "Name": "Brand"}]
    body = body_of(req)
    assert body["AccountIds"] == [ACCOUNT] and body["FormatVersion"] == "6.0"
