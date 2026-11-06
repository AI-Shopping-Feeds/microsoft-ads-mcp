"""Quick edits across many entities: pause/enable and relative bid changes."""

from __future__ import annotations

from typing import Any

from .. import safety
from ..client import MicrosoftAdsClient
from . import ad_groups, ads, asset_groups, campaigns, keywords
from ._common import PARENTS, EntitySpec, fetch, ids_to_strings, need_id, with_errors

ENTITIES: dict[str, EntitySpec] = {
    "campaigns": campaigns.SPEC,
    "ad_groups": ad_groups.SPEC,
    "asset_groups": asset_groups.SPEC,
    "ads": ads.SPEC,
    "keywords": keywords.SPEC,
}
BID_ENTITIES = {"ad_groups": ("CpcBid", ad_groups.SPEC), "keywords": ("Bid", keywords.SPEC)}
STATUSES = {"active": "Active", "paused": "Paused"}


def _entity(name: str, table: dict[str, Any]) -> Any:
    key = name.strip().lower().replace(" ", "_").replace("-", "_")
    if key not in table:
        raise ValueError(f"entity must be one of {', '.join(table)}.")
    return key, table[key]


def register(mcp, client: MicrosoftAdsClient) -> None:
    @mcp.tool()
    def microsoft_ads_set_status(
        entity: str,
        ids: list[str],
        status: str,
        parent_id: str | None = None,
        account_id: str | None = None,
        customer_id: str | None = None,
        confirm: str = "",
    ) -> dict[str, Any]:
        """Pause or enable many campaigns, ad groups, asset groups, ads or keywords at once.

        entity: campaigns, ad_groups, asset_groups, ads or keywords. status: Active or
        Paused. parent_id is the campaign ID for ad_groups/asset_groups and the ad group
        ID for ads/keywords (not needed for campaigns). Current statuses are read first
        and kept in the audit log. Setting campaigns Active starts spending, so it needs
        confirm='APPLY', as do batches over MICROSOFT_ADS_BULK_THRESHOLD.
        """
        noun, spec = _entity(entity, ENTITIES)
        new_status = STATUSES.get(status.strip().lower())
        if new_status is None:
            raise ValueError("status must be Active or Paused.")
        id_list = ids_to_strings(ids)
        if not id_list:
            raise ValueError("Pass at least one ID.")
        if len(id_list) > spec.max_items:
            raise ValueError(f"At most {spec.max_items} {noun} per call.")
        current, _, _ = fetch(
            client,
            spec,
            parent_id=parent_id,
            ids=id_list,
            account_id=account_id,
            customer_id=customer_id,
            max_results=len(id_list),
        )
        by_id = {str(c.get("Id")): c for c in current}
        missing = [i for i in id_list if i not in by_id]
        if missing:
            raise ValueError(f"Not found (check parent_id and account): {missing[:10]}")
        items = []
        for i in id_list:
            item: dict[str, Any] = {"Id": i, "Status": new_status}
            if spec.needs_type:
                item["Type"] = by_id[i].get("Type")
            items.append(item)
        always = (
            "enabling campaigns starts spending"
            if noun == "campaigns" and new_status == "Active"
            else None
        )
        decision = safety.assess(client.config, count=len(items), always=always)
        changes = [{"id": i, "from": by_id[i].get("Status"), "to": new_status} for i in id_list]
        body: dict[str, Any] = {spec.resource: items}
        if spec.parent == "account":
            body["AccountId"] = client.account(account_id)
        else:
            body[str(PARENTS[spec.parent][0])] = need_id(parent_id, "parent_id")
        refused = safety.refusal(client.config, decision, confirm, preview={"changes": changes})
        if refused:
            return refused
        out = client.request(
            "PUT",
            spec.path,
            body=body,
            account_id=account_id,
            customer_id=customer_id,
            op=f"set_status_{noun}",
            before=current,
        )
        return safety.annotate({**with_errors(out), "changes": changes}, decision)

    @mcp.tool()
    def microsoft_ads_adjust_bids(
        entity: str,
        parent_id: str,
        ids: list[str],
        percent: float,
        min_bid: float = 0.05,
        max_bid: float | None = None,
        account_id: str | None = None,
        customer_id: str | None = None,
        confirm: str = "",
    ) -> dict[str, Any]:
        """Raise or lower ad group default bids or keyword bids by a percentage.

        entity: ad_groups (parent_id = campaign ID) or keywords (parent_id = ad group
        ID). percent: e.g. -10 lowers by 10%, 15 raises by 15%. New bids are rounded
        to 2 decimals and kept within min_bid and max_bid. Current bids are read first;
        entities without their own bid are skipped. Rises above
        MICROSOFT_ADS_MAX_INCREASE_PCT, or over MICROSOFT_ADS_MAX_BID, and large batches
        need confirm='APPLY'.
        """
        noun, (field, spec) = _entity(entity, BID_ENTITIES)
        id_list = ids_to_strings(ids)
        if not id_list:
            raise ValueError("Pass at least one ID.")
        if percent <= -100:
            raise ValueError("percent must be greater than -100.")
        current, _, _ = fetch(
            client,
            spec,
            parent_id=parent_id,
            ids=id_list,
            account_id=account_id,
            customer_id=customer_id,
            max_results=len(id_list),
        )
        items: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for c in current:
            old = safety._num(safety.dig(c, (field, "Amount")))
            if old is None:
                skipped.append({"id": c.get("Id"), "reason": f"no {field} set"})
                continue
            new = round(old * (1 + percent / 100), 2)
            new = max(min_bid, new)
            if max_bid is not None:
                new = min(max_bid, new)
            if new != old:
                items.append({"Id": str(c.get("Id")), field: {"Amount": new}})
        if not items:
            return {"changed": 0, "skipped": skipped, "message": "Nothing to change."}
        changes = safety.money_changes(items, current, fields=spec.money)
        decision = safety.assess(client.config, count=len(items), changes=changes)
        body = {
            "AdGroupId" if noun == "keywords" else "CampaignId": parent_id,
            spec.resource: items,
        }
        refused = safety.refusal(client.config, decision, confirm, preview=body)
        if refused:
            return refused
        out = client.request(
            "PUT",
            spec.path,
            body=body,
            account_id=account_id,
            customer_id=customer_id,
            op=f"adjust_bids_{noun}",
            before=current,
        )
        return safety.annotate(
            {**with_errors(out), "changed": len(items), "skipped": skipped}, decision
        )
