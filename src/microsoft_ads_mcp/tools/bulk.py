"""Bulk service download: a whole account's entities as rows, in one file.

Useful for an overview of large accounts. Upload (bulk changes) isn't offered:
use the entity tools, which check and audit each change.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from mcp.server.mcpserver import Context

from ..client import MicrosoftAdsClient
from ._progress import report, run_blocking

DEFAULT_ENTITIES = ["Campaigns", "AdGroups", "Ads", "Keywords"]


def register(mcp, client: MicrosoftAdsClient) -> None:
    @mcp.tool()
    async def microsoft_ads_bulk_download(
        download_entities: list[str] | None = None,
        data_scope: str = "EntityData",
        last_sync_time_utc: str | None = None,
        max_rows: int = 2000,
        timeout_seconds: float = 900,
        poll_seconds: float = 10,
        account_id: str | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Download one account's entities with the Bulk service and return the rows.

        download_entities: e.g. Campaigns, AdGroups, Ads, Keywords (default),
        CampaignNegativeKeywords, AdGroupNegativeKeywords, AssetGroups, Budgets, Labels.
        data_scope: EntityData (default) or 'EntityData, QualityScoreData'.
        last_sync_time_utc (ISO 8601, within the last 30 days) returns only changes since
        then. Each row is one record from the bulk file (its Type column says what it is).
        Rows stay in memory; files over MICROSOFT_ADS_MAX_DOWNLOAD_MB are refused.
        """
        aid = client.account(account_id)
        body: dict[str, Any] = {
            "AccountIds": [aid],
            "DownloadEntities": download_entities or DEFAULT_ENTITIES,
            "DataScope": data_scope,
            "DownloadFileType": "Csv",
            "FormatVersion": "6.0",
            "CompressionType": "Zip",
        }
        if last_sync_time_utc:
            body["LastSyncTimeInUTC"] = last_sync_time_utc
        out = await run_blocking(
            client.request,
            "POST",
            "/Bulk/v13/Campaigns/DownloadByAccountIds",
            body=body,
            account_id=aid,
            read_only=True,
        )
        request_id = (out or {}).get("DownloadRequestId")
        if not request_id:
            raise RuntimeError(f"No DownloadRequestId in the response: {out}")
        step = 1
        await report(ctx, step, None, f"Requested bulk download {request_id}")
        deadline = time.monotonic() + timeout_seconds
        while True:
            status = await run_blocking(
                client.request,
                "POST",
                "/Bulk/v13/BulkDownloadStatus/Query",
                body={"RequestId": request_id},
                account_id=aid,
                read_only=True,
            )
            state = status.get("RequestStatus")
            step += 1
            if state == "Completed":
                url = status.get("ResultFileUrl")
                raw = await run_blocking(client.download, url) if url else b""
                rows = client.parse_csv_file(raw) if raw else []
                await report(ctx, step, None, f"Downloaded {len(rows)} rows")
                return {
                    "request_id": request_id,
                    "status": state,
                    "row_count": len(rows),
                    "rows": rows[: max(0, max_rows)],
                    "truncated": len(rows) > max_rows,
                }
            if state not in ("InProgress", "Pending", None):
                return {
                    "request_id": request_id,
                    "status": state,
                    "errors": status.get("Errors"),
                    "message": "FailedFullSyncRequired means: try again without last_sync_time_utc."
                    if state == "FailedFullSyncRequired"
                    else "The bulk download failed.",
                }
            if time.monotonic() >= deadline:
                return {"request_id": request_id, "status": state, "message": "Still running."}
            pct = status.get("PercentComplete")
            await report(ctx, step, None, f"Bulk download {state} {pct or 0}%")
            await asyncio.sleep(max(0.0, poll_seconds))
