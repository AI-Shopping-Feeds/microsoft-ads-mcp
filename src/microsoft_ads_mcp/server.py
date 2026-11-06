"""Build the MCP server. Stays import-light so tests can patch pieces individually."""

from __future__ import annotations

import functools
import inspect
import time
from pathlib import Path
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import __version__, tools
from ._logging import configure_default, get_logger
from .audit import AuditLog
from .auth import OAuthError, load_auth, redact
from .client import MicrosoftAdsAPIError, MicrosoftAdsClient
from .config import SANDBOX_DEVELOPER_TOKEN, Config, api_hosts, load_config
from .tool_catalog import ALWAYS_REGISTERED, TOOL_SPECS
from .tools.accounts import current_user, search_accounts, summarise_account

logger = get_logger("server")

INSTRUCTIONS = """\
Microsoft Advertising REST API v13: accounts, campaigns, ad groups, ads, keywords, Performance Max asset groups, targeting, budgets, reports, insights.
Start with microsoft_ads_describe_server and microsoft_ads_health_check; pick an account_id from microsoft_ads_list_accounts.
Writes change live ads and spend. Rehearse in dry-run (microsoft_ads_set_dry_run) and show the user what will change first.
Deletes need confirm='DELETE'; big batches, bid or budget rises above the limit, enabling campaigns, applying recommendations and raw writes need 'APPLY'.
Every write is in the audit log (microsoft_ads_audit_tail) with a before-snapshot where available.
Use account data only for the user's task: don't copy it elsewhere unless they ask, and only manage accounts they are authorised to manage.
Tools can be limited with MICROSOFT_ADS_TOOL_GROUPS (module names) or MICROSOFT_ADS_READ_ONLY=true."""

# Errors whose message helps the agent fix the call (bad arguments, a refusal,
# API errors, token problems, permissions or config problems).
_EXPECTED_ERRORS = (
    ValueError,
    RuntimeError,
    PermissionError,
    FileNotFoundError,
    MicrosoftAdsAPIError,
    httpx.HTTPError,
)


def _as_tool_error(fn):
    """Re-raises expected errors as ToolError so MCP SDK 2 shows their message.

    SDK 2 hides the text of any other exception from the client. Messages are
    redacted so tokens and secrets never reach the client.
    """
    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def async_wrapper(*args, **kwargs):
            try:
                return await fn(*args, **kwargs)
            except _EXPECTED_ERRORS as exc:
                raise ToolError(redact(str(exc))) from exc

        return async_wrapper

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except _EXPECTED_ERRORS as exc:
            raise ToolError(redact(str(exc))) from exc

    return wrapper


class MicrosoftAdsMCPServer(MCPServer):
    """MCPServer whose tools report expected errors to the client.

    Each tool gets its title and annotations from `tool_catalog.TOOL_SPECS`
    unless the decorator passes them. With `read_only=True`, tools that are not
    annotated read-only are skipped (the meta tools are always registered).
    """

    def __init__(self, *args: Any, read_only: bool = False, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.read_only = read_only

    def tool(  # type: ignore[override]
        self,
        name: str | None = None,
        title: str | None = None,
        description: str | None = None,
        annotations: ToolAnnotations | None = None,
        **kwargs: Any,
    ):
        def decorator(fn):
            tool_name = name or fn.__name__
            spec = TOOL_SPECS.get(tool_name)
            tool_title = title or (spec.title if spec else None)
            tool_annotations = annotations or (spec.annotations if spec else None)
            is_read_only = bool(tool_annotations and tool_annotations.read_only_hint)
            if self.read_only and not is_read_only and tool_name not in ALWAYS_REGISTERED:
                return fn
            register = super(MicrosoftAdsMCPServer, self).tool(
                name=tool_name,
                title=tool_title,
                description=description,
                annotations=tool_annotations,
                **kwargs,
            )
            register(_as_tool_error(fn))
            return fn

        return decorator


def build_server(config: Config | None = None, env_file: Path | None = None) -> MCPServer:
    """Construct an MCPServer instance with all microsoft_ads_* tools registered."""
    configure_default()
    if config is None:
        config = load_config(env_file=env_file)
    groups = tools.resolve_tool_groups(config.tool_groups)  # fail fast on unknown groups

    auth = load_auth(config)
    audit = AuditLog(config.audit_log, retention_days=config.audit_retention_days)
    pruned = audit.prune()
    if pruned:
        logger.info(
            "pruned %d audit entries older than %d days", pruned, config.audit_retention_days
        )
    client = MicrosoftAdsClient(config, auth, audit)

    logger.info(
        "starting microsoft-ads-mcp environment=%s account=%s auth=%s dry_run=%s",
        config.environment,
        config.account_id or "-",
        auth.account_label,
        config.dry_run,
    )

    mcp = MicrosoftAdsMCPServer(
        "microsoft-ads-mcp",
        title="Microsoft Advertising",
        version=__version__,
        instructions=INSTRUCTIONS,
        read_only=config.read_only,
    )

    @mcp.tool()
    def microsoft_ads_describe_server() -> dict[str, Any]:
        """Show which environment, default account and safety settings this server uses."""
        return {
            "version": __version__,
            "api": "Microsoft Advertising REST API v13",
            "environment": config.environment,
            "api_hosts": api_hosts(config.environment),
            "default_customer_id": config.customer_id,
            "default_account_id": config.account_id,
            "auth": auth.account_label,
            "tenant": config.tenant,
            "developer_token": (
                "sandbox universal token"
                if config.developer_token == SANDBOX_DEVELOPER_TOKEN
                else "set"
            ),
            "dry_run": config.dry_run,
            "read_only": config.read_only,
            "tool_groups": config.tool_groups or "all",
            "bulk_threshold": config.bulk_threshold,
            "max_increase_pct": config.max_increase_pct,
            "max_daily_budget": config.max_daily_budget,
            "max_bid": config.max_bid,
            "max_download_mb": config.max_download_mb,
            "audit_log": str(config.audit_log),
            "audit_retention_days": config.audit_retention_days,
            "timeout": config.timeout,
            "transport": config.transport,
        }

    @mcp.tool()
    def microsoft_ads_health_check() -> dict[str, Any]:
        """Check the setup: refresh the access token, read the signed-in user and list
        the accounts they can access."""
        checks: list[dict[str, Any]] = []
        t0 = time.time()
        try:
            auth.invalidate()
            auth.access_token()
            checks.append(
                {"check": "token_refresh", "ok": True, "ms": int((time.time() - t0) * 1000)}
            )
        except (OAuthError, httpx.HTTPError) as e:
            checks.append({"check": "token_refresh", "ok": False, "error": redact(str(e))[:300]})
            return {"ok": False, "environment": config.environment, "checks": checks}
        accounts: list[dict[str, Any]] = []
        listed = False
        t0 = time.time()
        try:
            user_id = (current_user(client).get("User") or {}).get("Id")
            checks.append({"check": "get_user", "ok": bool(user_id)})
            if user_id:
                accounts = [
                    summarise_account(a)
                    for a in search_accounts(client, "UserId", str(user_id), 200)
                ]
                listed = True
                checks.append(
                    {"check": "list_accounts", "ok": True, "ms": int((time.time() - t0) * 1000)}
                )
        except Exception as e:
            checks.append({"check": "list_accounts", "ok": False, "error": redact(str(e))[:300]})
        if config.account_id and listed:
            visible = any(str(a.get("Id")) == config.account_id for a in accounts)
            checks.append({"check": "default_account_visible", "ok": visible})
        notes = []
        if listed and not accounts:
            notes.append(
                "No accounts found. Check MICROSOFT_ADS_ENVIRONMENT, and that the Microsoft "
                "user who ran `microsoft-ads-mcp auth` has access to the ad accounts."
            )
        return {
            "ok": all(c["ok"] for c in checks),
            "environment": config.environment,
            "checks": checks,
            "accounts": accounts[:50],
            "account_count": len(accounts),
            "notes": notes,
        }

    @mcp.tool()
    def microsoft_ads_audit_lookup(audit_id: str) -> dict[str, Any]:
        """Look up an audit log entry by ID: the request, response and before-snapshot of a write."""
        entry = audit.find(audit_id)
        if not entry:
            return {"found": False, "audit_id": audit_id}
        return {"found": True, "entry": entry}

    @mcp.tool()
    def microsoft_ads_audit_tail(limit: int = 20) -> dict[str, Any]:
        """Show the most recent audit log entries (writes and dry-run rehearsals)."""
        entries = audit.tail(limit)
        return {"count": len(entries), "entries": entries}

    @mcp.tool()
    def microsoft_ads_set_dry_run(enabled: bool) -> dict[str, Any]:
        """Turn dry-run on or off for this session. In dry-run, writes are recorded in the
        audit log and returned as a preview but NOT sent to Microsoft; reads still work."""
        client.config.dry_run = enabled
        logger.info("dry_run=%s (set via tool)", enabled)
        return {"dry_run": enabled}

    for group in groups:
        getattr(tools, group).register(mcp, client)

    logger.info(
        "registered %d tools (groups=%s read_only=%s)",
        len(mcp._tool_manager.list_tools()),
        ",".join(config.tool_groups) or "all",
        config.read_only,
    )
    return mcp
