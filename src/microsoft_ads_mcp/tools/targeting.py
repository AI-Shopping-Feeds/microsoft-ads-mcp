"""Audiences and campaign or ad group criterions (targets, bid adjustments, exclusions).

In Microsoft Advertising, targeting and audience associations are criterions:
location, radius, age, gender, device, day and time, audience lists, product
partitions and so on, each attached to a campaign or an ad group.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .. import safety
from ..client import MicrosoftAdsClient
from ._common import CM, check_items, ids_to_strings, need_id, with_errors

LEVELS = {
    "ad_group": ("AdGroupCriterions", "AdGroupId", "AdGroupCriterionIds"),
    "campaign": ("CampaignCriterions", "CampaignId", "CampaignCriterionIds"),
}
DEFAULT_AUDIENCE_TYPES = (
    "RemarketingList, Custom, InMarket, Product, SimilarRemarketingList, CombinedList, CustomerList"
)
CRITERION_TYPES_HELP = (
    "criterion_type is one Microsoft criterion type, e.g. Location, Radius, Age, Gender, "
    "DayTime, Device, LocationIntent, Audience (associations), ProductPartition (Shopping ad "
    "groups) or Webpage."
)


def _level(value: str) -> tuple[str, str, str]:
    key = value.strip().lower().replace(" ", "_").replace("adgroup", "ad_group")
    if key not in LEVELS:
        raise ValueError("level must be 'campaign' or 'ad_group'.")
    return LEVELS[key]


def register(mcp, client: MicrosoftAdsClient) -> None:
    @mcp.tool()
    def microsoft_ads_list_audiences(
        ids: list[str] | None = None,
        audience_types: str = DEFAULT_AUDIENCE_TYPES,
        account_id: str | None = None,
        customer_id: str | None = None,
    ) -> dict[str, Any]:
        """List audiences (remarketing, custom, in-market, product, similar, combined,
        customer match lists). Without ids, all audiences of audience_types are returned.

        Attach an audience with microsoft_ads_add_criterions (criterion Type
        AudienceCriterion with AudienceId and AudienceType).
        """
        body: dict[str, Any] = {"Type": audience_types}
        if ids:
            body["AudienceIds"] = ids_to_strings(ids)
        out = client.request(
            "POST",
            f"{CM}/Audiences/QueryByIds",
            body=body,
            account_id=account_id,
            customer_id=customer_id,
            read_only=True,
        )
        if isinstance(out, dict):
            out = {**out, "Audiences": [a for a in out.get("Audiences") or [] if a]}
        return with_errors(out)

    def fetch(level, parent_id, criterion_type, ids, account_id, customer_id):
        resource, parent_key, ids_key = _level(level)
        body: dict[str, Any] = {
            parent_key: need_id(parent_id, "parent_id"),
            "CriterionType": criterion_type,
        }
        if ids:
            body[ids_key] = ids_to_strings(ids)
        out = client.request(
            "POST",
            f"{CM}/{resource}/QueryByIds",
            body=body,
            account_id=account_id,
            customer_id=customer_id,
            read_only=True,
        )
        return [c for c in (out.get(resource) or []) if c]

    @mcp.tool(
        description=(
            "List the criterions (targets, exclusions, bid adjustments, audience associations) "
            "of one campaign or ad group.\n\nlevel: 'campaign' or 'ad_group'. parent_id: the "
            "campaign or ad group ID. " + CRITERION_TYPES_HELP + " Pass ids to get specific "
            "criterions; otherwise all of that type are returned."
        )
    )
    def microsoft_ads_list_criterions(
        level: str,
        parent_id: str,
        criterion_type: str,
        ids: list[str] | None = None,
        account_id: str | None = None,
        customer_id: str | None = None,
    ) -> dict[str, Any]:
        items = fetch(level, parent_id, criterion_type, ids, account_id, customer_id)
        return {"criterions": items, "count": len(items)}

    def write(method, op, level, criterion_type, items, account_id, customer_id, confirm):
        resource, parent_key, _ = _level(level)
        check_items(items, "criterions", 1000)
        missing = [i for i, it in enumerate(items) if not it.get(parent_key) or not it.get("Type")]
        if missing:
            raise ValueError(
                f"Every criterion needs {parent_key} and Type; missing at {missing[:10]}."
            )
        before = None
        changes: list[safety.MoneyChange] = []
        if method == "PUT":
            by_parent: dict[str, list[str]] = defaultdict(list)
            for it in items:
                if it.get("Id"):
                    by_parent[str(it[parent_key])].append(str(it["Id"]))
            current: list[Any] = []
            for pid, cids in by_parent.items():
                got = client.snapshot(
                    fetch, level, pid, criterion_type, cids, account_id, customer_id
                )
                current.extend(got or [])
            before = current
            changes = safety.money_changes(items, current, fields=safety.CRITERION_MONEY)
        else:
            changes = safety.new_values(items, safety.CRITERION_MONEY)
        decision = safety.assess(
            client.config, count=len(items), changes=changes, creating=method == "POST"
        )
        body = {resource: items, "CriterionType": criterion_type}
        refused = safety.refusal(client.config, decision, confirm, preview=body)
        if refused:
            return refused
        out = client.request(
            method,
            f"{CM}/{resource}",
            body=body,
            account_id=account_id,
            customer_id=customer_id,
            op=op,
            before=before,
        )
        return safety.annotate(with_errors(out), decision)

    @mcp.tool(
        description=(
            "Add criterions to campaigns or ad groups: targets, exclusions, bid adjustments "
            "and audience associations. Changes the live account.\n\nlevel: 'campaign' or "
            "'ad_group'. " + CRITERION_TYPES_HELP + " items use Microsoft's field names and each "
            "needs CampaignId or AdGroupId and Type, e.g. a UK location target on a campaign: "
            '{"CampaignId": "123", "Type": "BiddableCampaignCriterion", "Criterion": {"Type": '
            '"LocationCriterion", "LocationId": "188"}, "CriterionBid": {"Type": '
            '"BidMultiplier", "Multiplier": 0}}. Use NegativeCampaignCriterion / '
            "NegativeAdGroupCriterion to exclude. Large batches need confirm='APPLY'."
        )
    )
    def microsoft_ads_add_criterions(
        level: str,
        criterion_type: str,
        items: list[dict[str, Any]],
        account_id: str | None = None,
        customer_id: str | None = None,
        confirm: str = "",
    ) -> dict[str, Any]:
        return write(
            "POST", "add_criterions", level, criterion_type, items, account_id, customer_id, confirm
        )

    @mcp.tool(
        description=(
            "Update criterions (e.g. bid adjustments or product partition bids). Changes the "
            "live account.\n\nitems: objects with Id, CampaignId or AdGroupId, Type and the "
            "fields to change. Current values are read first and kept in the audit log; fixed "
            "bid rises above MICROSOFT_ADS_MAX_INCREASE_PCT and large batches need "
            "confirm='APPLY'. " + CRITERION_TYPES_HELP
        )
    )
    def microsoft_ads_update_criterions(
        level: str,
        criterion_type: str,
        items: list[dict[str, Any]],
        account_id: str | None = None,
        customer_id: str | None = None,
        confirm: str = "",
    ) -> dict[str, Any]:
        return write(
            "PUT",
            "update_criterions",
            level,
            criterion_type,
            items,
            account_id,
            customer_id,
            confirm,
        )

    @mcp.tool()
    def microsoft_ads_delete_criterions(
        level: str,
        parent_id: str,
        criterion_type: str,
        ids: list[str],
        account_id: str | None = None,
        customer_id: str | None = None,
        confirm: str = "",
    ) -> dict[str, Any]:
        """Delete criterions from one campaign or ad group (removes targets, exclusions or
        audience associations). Needs confirm='DELETE' after the user agrees; the current
        criterions are saved in the audit log first."""
        resource, parent_key, ids_key = _level(level)
        id_list = ids_to_strings(ids)
        if not id_list:
            raise ValueError("Pass at least one criterion ID.")
        body = {
            parent_key: need_id(parent_id, "parent_id"),
            "CriterionType": criterion_type,
            ids_key: id_list,
        }
        decision = safety.assess(client.config, count=len(id_list), destructive=safety.DELETE)
        refused = safety.refusal(client.config, decision, confirm, preview=body)
        if refused:
            return refused
        before = client.snapshot(
            fetch, level, parent_id, criterion_type, id_list, account_id, customer_id
        )
        out = client.request(
            "DELETE",
            f"{CM}/{resource}",
            body=body,
            account_id=account_id,
            customer_id=customer_id,
            op="delete_criterions",
            before=before,
        )
        return safety.annotate(with_errors(out), decision)
