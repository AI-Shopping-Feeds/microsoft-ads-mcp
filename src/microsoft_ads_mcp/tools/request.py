"""Escape hatch: call any Microsoft Advertising REST v13 operation by path."""

from __future__ import annotations

from typing import Any

from .. import safety
from ..client import MicrosoftAdsClient, split_path

# Last path segments of POST operations that only read.
_READ_SEGMENTS = {"search", "find", "poll", "retrieve"}
_READ_PREFIXES = ("query",)
# Report requests and bulk downloads change nothing in the account.
_READ_BY_SERVICE = {
    "Reporting": {"submit"},
    "Bulk": {"downloadbyaccountids", "downloadbycampaignids"},
}


def classify(method: str, path: str) -> tuple[str, str, bool]:
    """Return (METHOD, path, is_read) for an escape-hatch call."""
    method = method.upper()
    if method not in {"POST", "PUT", "DELETE"}:
        raise ValueError("method must be POST, PUT or DELETE (the REST API uses no GETs).")
    service, path = split_path(path)
    last = path.rstrip("/").rsplit("/", 1)[-1].lower()
    is_read = method == "POST" and (
        last in _READ_SEGMENTS
        or last.startswith(_READ_PREFIXES)
        or last in _READ_BY_SERVICE.get(service, set())
    )
    return method, path, is_read


def register(mcp, client: MicrosoftAdsClient) -> None:
    @mcp.tool()
    def microsoft_ads_read_request(
        path: str,
        body: dict[str, Any] | None = None,
        account_id: str | None = None,
        customer_id: str | None = None,
    ) -> Any:
        """Call any read-only Microsoft Advertising REST operation the other tools don't cover.

        path is a v13 REST path such as '/CampaignManagement/v13/SharedEntities/QueryByAccountId'
        or '/CampaignManagement/v13/AdExtensions/QueryByIds' (find it in Microsoft's REST
        reference). Only POSTs whose last segment is Query..., Search, Find, Poll or Retrieve
        (plus report submits and bulk downloads) are allowed; use microsoft_ads_request for
        anything that changes the account. The host is chosen from the path and environment;
        other hosts can't be reached.
        """
        method, path, is_read = classify("POST", path)
        if not is_read:
            raise ValueError(f"POST {path} may change the account; use microsoft_ads_request.")
        return client.request(
            method,
            path,
            body=body or {},
            account_id=account_id,
            customer_id=customer_id,
            read_only=True,
        )

    @mcp.tool()
    def microsoft_ads_request(
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        account_id: str | None = None,
        customer_id: str | None = None,
        confirm: str = "",
    ) -> Any:
        """Call any Microsoft Advertising REST v13 operation the other tools don't cover.

        method: POST, PUT or DELETE. path, e.g. '/CampaignManagement/v13/AdExtensions'
        (add), '/CampaignManagement/v13/SharedEntityAssociations/Set'. Read operations
        behave as in microsoft_ads_read_request. Every other call is a write: it follows
        dry-run, is audited, and needs confirm='APPLY' because this tool can't check what
        it changes. CustomerId and CustomerAccountId headers are sent from account_id /
        customer_id or the configured defaults.
        """
        method, path, is_read = classify(method, path)
        if not is_read:
            decision = safety.Decision(
                required=safety.APPLY,
                reasons=["raw write through microsoft_ads_request; its effect isn't checked"],
            )
            refused = safety.refusal(
                client.config,
                decision,
                confirm,
                preview={"method": method, "path": path, "body": body},
            )
            if refused:
                return refused
        return client.request(
            method,
            path,
            body=body or {},
            account_id=account_id,
            customer_id=customer_id,
            read_only=is_read,
            op=f"request {method} {path}",
        )
