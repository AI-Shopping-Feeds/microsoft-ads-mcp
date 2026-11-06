"""Thin HTTP client for the Microsoft Advertising REST API (v13).

Every API call goes through `MicrosoftAdsClient.request`, the one choke point
for auth headers, account scoping, retries, dry-run, the audit log and
redaction. It only talks to the Microsoft Advertising API hosts for the
configured environment; report and bulk files are fetched from the signed
download link the API returns, and only from Microsoft-operated hosts.
"""

from __future__ import annotations

import csv
import io
import json
import random
import threading
import time
import zipfile
from typing import Any
from urllib.parse import urlparse

import httpx

from . import __version__
from ._logging import get_logger
from .audit import AuditLog
from .auth import Auth, redact
from .config import API_VERSION, SERVICE_HOSTS, Config

RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 5
MAX_BACKOFF = 120.0  # cap on honouring a very long Retry-After
# Microsoft asks callers to wait 60 seconds after CallRateExceeded (code 117).
CALL_RATE_WAIT = 60.0
CALL_RATE_CODES = {"117", "CallRateExceeded"}
# Customer Management and Customer Billing don't take the CustomerId and
# CustomerAccountId headers.
UNSCOPED_SERVICES = {"CustomerManagement", "CustomerBilling"}
# Report and bulk files come from a short-lived signed link. Microsoft says not
# to depend on its domain, so allow Microsoft-operated hosts and Azure Blob
# Storage (where the signed links point) over HTTPS, and nothing else.
DOWNLOAD_HOST_SUFFIXES = (".microsoft.com", ".blob.core.windows.net")

logger = get_logger("client")


def error_details(payload: Any, limit: int = 20) -> list[dict[str, Any]]:
    """Collect {Code, ErrorCode, Message, ...} objects from an error or PartialErrors body."""
    found: list[dict[str, Any]] = []

    def walk(obj: Any) -> None:
        if len(found) >= limit:
            return
        if isinstance(obj, dict):
            if "ErrorCode" in obj or ("Code" in obj and "Message" in obj):
                found.append(
                    {
                        k: obj[k]
                        for k in ("Code", "ErrorCode", "Message", "FieldPath", "Index", "Details")
                        if obj.get(k) not in (None, "")
                    }
                )
                return
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(payload)
    return found


def error_codes(payload: Any) -> set[str]:
    codes: set[str] = set()
    for e in error_details(payload, limit=100):
        for key in ("Code", "ErrorCode"):
            if e.get(key) is not None:
                codes.add(str(e[key]))
    return codes


class MicrosoftAdsAPIError(Exception):
    def __init__(self, status: int, body: Any, message: str = ""):
        self.status = status
        self.body = redact(body)
        self.codes = error_codes(body)
        if not message:
            details = error_details(self.body)
            tracking = self.body.get("TrackingId") if isinstance(self.body, dict) else None
            summary: Any = details or self.body
            message = f"Microsoft Advertising API error {status}: {summary}"
            if tracking:
                message += f" (TrackingId {tracking})"
            if {"105", "106"} & self.codes:
                message += (
                    ". Code 105 usually means the access token or developer token is for the "
                    "other environment (production vs sandbox); 106 means this user can't "
                    "access the customer or account in the request."
                )
        super().__init__(message)


def split_path(path: str) -> tuple[str, str]:
    """Check a REST path and return (service, path without query string).

    Paths look like /CampaignManagement/v13/Campaigns/QueryByIds. Only the
    known service prefixes and API version are accepted, so a path can't point
    the request at another host or version.
    """
    if not isinstance(path, str) or not path.startswith("/"):
        raise ValueError("path must start with '/', e.g. '/CampaignManagement/v13/Campaigns'.")
    if "://" in path or ".." in path or "\\" in path or "?" in path or "#" in path:
        raise ValueError("path must be a plain API path: no scheme, '..', query or fragment.")
    if any(ch.isspace() for ch in path) or "%" in path:
        raise ValueError("path must not contain spaces or percent-encoding.")
    parts = path.split("/")
    if len(parts) < 4 or parts[1] not in SERVICE_HOSTS or parts[2] != API_VERSION:
        raise ValueError(
            f"path must start with /<Service>/{API_VERSION}/ where Service is one of "
            f"{', '.join(sorted(SERVICE_HOSTS))}."
        )
    return parts[1], path


class MicrosoftAdsClient:
    """Thin HTTP wrapper over the Microsoft Advertising REST API.

    Adds the OAuth, developer-token and account-scope headers, retries throttled
    and failed requests with backoff (honouring Retry-After and Microsoft's
    60-second wait after CallRateExceeded), and sends every write through
    dry-run and the audit log.
    """

    def __init__(self, config: Config, auth: Auth, audit: AuditLog):
        self.config = config
        self.auth = auth
        self.audit = audit
        self._http = httpx.Client(
            timeout=config.timeout,
            headers={"User-Agent": f"microsoft-ads-mcp/{__version__}"},
            follow_redirects=False,
        )
        self._parent_customer: dict[str, str] = {}
        self._lock = threading.Lock()

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> MicrosoftAdsClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------ scoping

    @staticmethod
    def _id(value: Any, name: str) -> str | None:
        if value in (None, ""):
            return None
        text = str(value).strip()
        if not text.isdigit():
            raise ValueError(f"{name} must be a numeric ID, got '{text}'.")
        return text

    def account(self, account_id: Any = None) -> str:
        """The account to act on: the argument, else MICROSOFT_ADS_ACCOUNT_ID."""
        aid = self._id(account_id, "account_id") or self.config.account_id
        if not aid:
            raise ValueError(
                "No account_id. Pass account_id (see microsoft_ads_list_accounts) or set "
                "MICROSOFT_ADS_ACCOUNT_ID."
            )
        return aid

    def scope(self, account_id: Any = None, customer_id: Any = None) -> tuple[str | None, str]:
        """Return (customer_id, account_id) for the CustomerId/CustomerAccountId headers.

        If no customer is given or configured, the account's parent customer is
        looked up once with GetAccount and cached.
        """
        aid = self.account(account_id)
        cid = self._id(customer_id, "customer_id")
        if cid:
            return cid, aid
        if self.config.customer_id and (account_id in (None, "") or aid == self.config.account_id):
            return self.config.customer_id, aid
        with self._lock:
            cached = self._parent_customer.get(aid)
        if cached:
            return cached, aid
        out = self.request(
            "POST",
            "/CustomerManagement/v13/Account/Query",
            body={"AccountId": aid},
            read_only=True,
        )
        parent = (
            (out.get("Account") or {}).get("ParentCustomerId") if isinstance(out, dict) else None
        )
        if not parent:
            return self.config.customer_id, aid
        with self._lock:
            self._parent_customer[aid] = str(parent)
        return str(parent), aid

    # ------------------------------------------------------------ requests

    def _headers(self, service: str, customer: str | None, account: str | None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.auth.access_token()}",
            "DeveloperToken": self.config.developer_token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if service not in UNSCOPED_SERVICES:
            if customer:
                headers["CustomerId"] = customer
            if account:
                headers["CustomerAccountId"] = account
        return headers

    def request(
        self,
        method: str,
        path: str,
        *,
        body: Any | None = None,
        account_id: Any = None,
        customer_id: Any = None,
        scoped: bool = True,
        op: str | None = None,
        before: Any | None = None,
        read_only: bool = False,
    ) -> Any:
        """Perform one API request and return parsed JSON ({} for an empty body).

        path: a REST path such as '/CampaignManagement/v13/Campaigns/QueryByIds';
            the host is chosen from its first segment and the environment.
        scoped: send CustomerId and CustomerAccountId (resolved from the
            arguments or the configured defaults). Ignored for Customer
            Management and Customer Billing, which don't take them.
        read_only: set True for POSTs that don't change anything (Query, Search,
            report and bulk-download requests). They bypass dry-run and the audit log.
        """
        method = method.upper()
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise ValueError("method must be GET, POST, PUT, PATCH or DELETE.")
        service, path = split_path(path)
        customer: str | None = None
        account: str | None = None
        if scoped and service not in UNSCOPED_SERVICES:
            customer, account = self.scope(account_id, customer_id)
        url = f"{self.config.base_url(service)}{path}"
        is_write = method != "GET" and not read_only
        op_name = op or f"{method} {path}"

        if is_write and self.config.dry_run:
            audit_id = self.audit.record(
                op=op_name,
                method=method,
                url=url,
                customer_id=customer,
                account_id=account,
                request_body=body,
                dry_run=True,
                before=before,
            )
            logger.info("dry-run %s %s (audit=%s)", method, path, audit_id)
            return {
                "_dry_run": True,
                "method": method,
                "url": url,
                "customer_id": customer,
                "account_id": account,
                "body": body,
                "audit_id": audit_id,
            }

        last_exc: Exception | None = None
        refreshed = False
        attempt = 0
        payload: Any = None
        while attempt < MAX_ATTEMPTS:
            try:
                resp = self._http.request(
                    method,
                    url,
                    content=None if body is None else json.dumps(body),
                    headers=self._headers(service, customer, account),
                )
            except httpx.RequestError as e:
                last_exc = e
                logger.warning("transport error attempt=%d %s %s: %s", attempt + 1, method, path, e)
                self._sleep_backoff(attempt)
                attempt += 1
                continue

            if resp.status_code == 401 and not refreshed:
                # The cached access token may have been revoked early; refresh once.
                refreshed = True
                self.auth.invalidate()
                continue

            payload = self._safe_json(resp)
            if (
                not (200 <= resp.status_code < 300)
                and CALL_RATE_CODES & error_codes(payload)
                and attempt < MAX_ATTEMPTS - 1
            ):
                logger.warning(
                    "CallRateExceeded on %s %s; waiting %ss", method, path, CALL_RATE_WAIT
                )
                time.sleep(CALL_RATE_WAIT)
                attempt += 1
                continue

            if resp.status_code in RETRYABLE_STATUSES and attempt < MAX_ATTEMPTS - 1:
                logger.warning(
                    "retryable status=%d attempt=%d %s %s",
                    resp.status_code,
                    attempt + 1,
                    method,
                    path,
                )
                self._sleep_backoff(attempt, resp)
                attempt += 1
                continue

            if not (200 <= resp.status_code < 300):
                if is_write:
                    self.audit.record(
                        op=op_name,
                        method=method,
                        url=url,
                        customer_id=customer,
                        account_id=account,
                        request_body=body,
                        response_status=resp.status_code,
                        response_body=payload,
                        before=before,
                        error=f"HTTP {resp.status_code}",
                    )
                logger.error(
                    "api error %d %s %s: %s", resp.status_code, method, path, redact(payload)
                )
                raise MicrosoftAdsAPIError(resp.status_code, payload)

            if is_write:
                audit_id = self.audit.record(
                    op=op_name,
                    method=method,
                    url=url,
                    customer_id=customer,
                    account_id=account,
                    request_body=body,
                    response_status=resp.status_code,
                    response_body=payload,
                    before=before,
                )
                logger.info(
                    "write %s %s -> %d (audit=%s)", method, path, resp.status_code, audit_id
                )
                if isinstance(payload, dict):
                    payload = {**payload, "audit_id": audit_id}
                else:
                    payload = {"result": payload, "audit_id": audit_id}
            else:
                logger.debug("read  %s %s -> %d", method, path, resp.status_code)
            return payload

        if payload is not None:
            raise MicrosoftAdsAPIError(429, payload)
        raise MicrosoftAdsAPIError(0, redact(str(last_exc)) if last_exc else "exhausted retries")

    def snapshot(self, fn: Any, *args: Any, **kwargs: Any) -> Any | None:
        """Run a read for a `before` snapshot; returns None instead of raising."""
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            logger.warning("before-snapshot failed: %s", redact(str(e)))
            return None

    # ------------------------------------------------------------ downloads

    @property
    def max_download_bytes(self) -> int:
        return max(1, self.config.max_download_mb) * 1024 * 1024

    def download(self, url: str) -> bytes:
        """Fetch a report or bulk file from its signed link, capped in size.

        The link is short-lived and carries its own signature, so no auth
        headers are sent with it.
        """
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not host.endswith(DOWNLOAD_HOST_SUFFIXES):
            raise ValueError(f"Refusing to download from a non-Microsoft host: {host!r}")
        cap = self.max_download_bytes
        last: Exception | None = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                with httpx.stream(
                    "GET", url, timeout=max(self.config.timeout, 120.0), follow_redirects=False
                ) as resp:
                    if resp.status_code in RETRYABLE_STATUSES and attempt < MAX_ATTEMPTS - 1:
                        self._sleep_backoff(attempt, resp)
                        continue
                    if resp.status_code != 200:
                        resp.read()
                        raise MicrosoftAdsAPIError(resp.status_code, resp.text[:300])
                    declared = int(resp.headers.get("Content-Length") or 0)
                    if declared > cap:
                        raise ValueError(self._too_big(declared))
                    buf = bytearray()
                    for chunk in resp.iter_bytes():
                        buf.extend(chunk)
                        if len(buf) > cap:
                            raise ValueError(self._too_big(len(buf)))
                    return bytes(buf)
            except httpx.RequestError as e:
                last = e
                self._sleep_backoff(attempt)
        raise MicrosoftAdsAPIError(0, redact(str(last)) if last else "download failed")

    def _too_big(self, size: int) -> str:
        return (
            f"The file is larger than MICROSOFT_ADS_MAX_DOWNLOAD_MB "
            f"({self.config.max_download_mb} MB; got at least {size // (1024 * 1024)} MB). "
            "Narrow the date range, columns or entities, or raise the limit."
        )

    def parse_csv_file(self, raw: bytes) -> list[dict[str, str]]:
        """Unzip (if zipped) and parse a CSV/TSV file into rows, in memory only."""
        cap = self.max_download_bytes
        if raw[:4] == b"PK\x03\x04":
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                members = [m for m in zf.infolist() if not m.is_dir()]
                if not members:
                    return []
                member = members[0]
                if member.file_size > cap:
                    raise ValueError(self._too_big(member.file_size))
                with zf.open(member) as f:
                    raw = f.read(cap + 1)
                if len(raw) > cap:
                    raise ValueError(self._too_big(len(raw)))
        text = raw.decode("utf-8-sig", errors="replace")
        if not text.strip():
            return []
        sample = text[:4096]
        delimiter = "\t" if sample.count("\t") > sample.count(",") else ","
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        return [dict(row) for row in reader]

    # ------------------------------------------------------------ helpers

    @staticmethod
    def _safe_json(resp: httpx.Response) -> Any:
        if resp.status_code == 204 or not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError:
            return {"_raw": resp.text[:2000]}

    @staticmethod
    def _sleep_backoff(attempt: int, resp: httpx.Response | None = None) -> None:
        retry_after = 0.0
        if resp is not None and "Retry-After" in resp.headers:
            try:
                retry_after = float(resp.headers["Retry-After"])
            except ValueError:
                retry_after = 0.0
        base = min(max(retry_after, min(2**attempt, 30)), MAX_BACKOFF)
        time.sleep(base + random.uniform(0, 0.5))
