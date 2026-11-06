"""Title and MCP annotations for every microsoft_ads_* tool.

`MicrosoftAdsMCPServer.tool()` looks each tool up here by name, so the tool
modules stay free of metadata. Every tool must have an entry:
tests/test_mcp_client.py fails if a registered tool is missing or an entry has
no tool.

Annotation kinds (all API tools are open-world: they call the Microsoft
Advertising API):

* READ: changes nothing in the account. Includes read-only POSTs (Query, Search).
* REPORT: requests a report or bulk download. Changes nothing in the account,
  but each call starts a new job, so it isn't idempotent.
* WRITE: creates something; repeating it creates it again.
* UPSERT: an update or state change; repeating it changes nothing more.
* DESTRUCTIVE: deletes or detaches; deleted entities can't be restored.
* DESTRUCTIVE_ONCE: the raw request tool, which may do anything.
* LOCAL_*: touches only this server (audit log, session settings).
"""

from __future__ import annotations

from typing import NamedTuple

from mcp.types import ToolAnnotations


def _ann(*, read_only: bool, destructive: bool, idempotent: bool, open_world: bool = True):
    return ToolAnnotations(
        read_only_hint=read_only,
        destructive_hint=destructive,
        idempotent_hint=idempotent,
        open_world_hint=open_world,
    )


READ = _ann(read_only=True, destructive=False, idempotent=True)
REPORT = _ann(read_only=True, destructive=False, idempotent=False)
WRITE = _ann(read_only=False, destructive=False, idempotent=False)
UPSERT = _ann(read_only=False, destructive=False, idempotent=True)
DESTRUCTIVE = _ann(read_only=False, destructive=True, idempotent=True)
DESTRUCTIVE_ONCE = _ann(read_only=False, destructive=True, idempotent=False)
LOCAL_READ = _ann(read_only=True, destructive=False, idempotent=True, open_world=False)
LOCAL_SETTING = _ann(read_only=False, destructive=False, idempotent=True, open_world=False)


class ToolSpec(NamedTuple):
    title: str
    annotations: ToolAnnotations


# Registered regardless of MICROSOFT_ADS_TOOL_GROUPS and MICROSOFT_ADS_READ_ONLY.
ALWAYS_REGISTERED = frozenset(
    {
        "microsoft_ads_describe_server",
        "microsoft_ads_health_check",
        "microsoft_ads_audit_lookup",
        "microsoft_ads_audit_tail",
        "microsoft_ads_set_dry_run",
    }
)


def _crud(noun: str, label: str) -> dict[str, tuple[str, ToolAnnotations]]:
    return {
        f"microsoft_ads_list_{noun}": (f"List {label}", READ),
        f"microsoft_ads_create_{noun}": (f"Create {label}", WRITE),
        f"microsoft_ads_update_{noun}": (f"Update {label}", UPSERT),
        f"microsoft_ads_delete_{noun}": (f"Delete {label}", DESTRUCTIVE),
    }


_CATALOG: dict[str, tuple[str, ToolAnnotations]] = {
    # server (meta)
    "microsoft_ads_describe_server": ("Describe the server configuration", LOCAL_READ),
    "microsoft_ads_health_check": ("Check the token and list accessible accounts", READ),
    "microsoft_ads_audit_lookup": ("Look up an audit log entry", LOCAL_READ),
    "microsoft_ads_audit_tail": ("Show recent audit log entries", LOCAL_READ),
    "microsoft_ads_set_dry_run": ("Turn dry-run mode on or off", LOCAL_SETTING),
    # accounts
    "microsoft_ads_get_user": ("Show the signed-in user and roles", READ),
    "microsoft_ads_list_accounts": ("List ad accounts", READ),
    "microsoft_ads_get_account": ("Get an ad account", READ),
    "microsoft_ads_list_customers": ("List customers (manager accounts)", READ),
    # campaigns, ad_groups, ads, keywords, asset_groups
    **_crud("campaigns", "campaigns"),
    **_crud("ad_groups", "ad groups"),
    **_crud("ads", "ads"),
    "microsoft_ads_create_responsive_search_ad": ("Create a responsive search ad", WRITE),
    **_crud("keywords", "keywords"),
    "microsoft_ads_list_negative_keywords": ("List campaign or ad group negative keywords", READ),
    "microsoft_ads_add_negative_keywords": ("Add negative keywords", WRITE),
    "microsoft_ads_delete_negative_keywords": ("Delete negative keywords", DESTRUCTIVE),
    **_crud("asset_groups", "Performance Max asset groups"),
    # targeting
    "microsoft_ads_list_audiences": ("List audiences", READ),
    "microsoft_ads_list_criterions": ("List targeting criterions", READ),
    "microsoft_ads_add_criterions": ("Add targeting criterions", WRITE),
    "microsoft_ads_update_criterions": ("Update targeting criterions", UPSERT),
    "microsoft_ads_delete_criterions": ("Delete targeting criterions", DESTRUCTIVE),
    # budgets
    **_crud("budgets", "shared budgets"),
    **_crud("bid_strategies", "portfolio bid strategies"),
    # labels
    **_crud("labels", "labels"),
    "microsoft_ads_list_label_associations": ("List label associations", READ),
    "microsoft_ads_set_label_associations": ("Attach labels", UPSERT),
    "microsoft_ads_delete_label_associations": ("Remove labels from entities", DESTRUCTIVE),
    # bulk_edits
    "microsoft_ads_set_status": ("Pause or enable many entities", UPSERT),
    "microsoft_ads_adjust_bids": ("Adjust many bids by a percentage", WRITE),
    # reporting
    "microsoft_ads_submit_report": ("Submit a report request", REPORT),
    "microsoft_ads_poll_report": ("Check a report's status", READ),
    "microsoft_ads_download_report": ("Download a finished report", READ),
    "microsoft_ads_run_report": ("Run a report and return its rows", REPORT),
    "microsoft_ads_change_history": ("Show account change history", REPORT),
    # insights
    "microsoft_ads_keyword_ideas": ("Get keyword ideas", READ),
    "microsoft_ads_keyword_traffic_estimates": ("Estimate keyword traffic", READ),
    "microsoft_ads_estimated_bids": ("Estimate bids for a position", READ),
    "microsoft_ads_budget_opportunities": ("Get budget opportunities", READ),
    "microsoft_ads_list_recommendations": ("List recommendations", READ),
    "microsoft_ads_apply_recommendations": ("Apply recommendations", WRITE),
    "microsoft_ads_dismiss_recommendations": ("Dismiss recommendations", UPSERT),
    # bulk
    "microsoft_ads_bulk_download": ("Download an account's entities in bulk", REPORT),
    # request
    "microsoft_ads_read_request": ("Read from any REST operation", READ),
    "microsoft_ads_request": ("Call any REST operation", DESTRUCTIVE_ONCE),
}

TOOL_SPECS: dict[str, ToolSpec] = {
    name: ToolSpec(title, annotations) for name, (title, annotations) in _CATALOG.items()
}
