"""Keywords and campaign or ad group negative keywords."""

from __future__ import annotations

from typing import Any

from .. import safety
from ..client import MicrosoftAdsClient
from ._common import CM, EntitySpec, ids_to_strings, need_id, register_entity, with_errors

SPEC = EntitySpec(
    noun="keywords",
    label="keywords",
    resource="Keywords",
    ids_key="KeywordIds",
    parent="ad_group",
    list_op="QueryByAdGroupId",
    max_items=1000,
    money=safety.KEYWORD_MONEY,
    create_example=(
        'e.g. {"Text": "running shoes", "MatchType": "Phrase", "Bid": {"Amount": 0.5}} '
        "(MatchType Exact, Phrase or Broad)."
    ),
    update_example='e.g. {"Id": "222", "Bid": {"Amount": 0.65}} or {"Id": "222", "Status": "Paused"}.',
)

ENTITY_TYPES = {"campaign": "Campaign", "adgroup": "AdGroup", "ad_group": "AdGroup"}
MATCH_TYPES = {"exact": "Exact", "phrase": "Phrase"}


def _entity_type(value: str) -> str:
    key = value.strip().lower().replace(" ", "")
    if key not in ENTITY_TYPES:
        raise ValueError("entity_type must be 'Campaign' or 'AdGroup'.")
    return ENTITY_TYPES[key]


def register(mcp, client: MicrosoftAdsClient) -> None:
    register_entity(mcp, client, SPEC)

    def fetch_negatives(entity_type, entity_ids, parent_id, account_id, customer_id):
        etype = _entity_type(entity_type)
        ids = ids_to_strings(entity_ids)
        if not ids:
            raise ValueError("Pass at least one entity ID.")
        parent = (
            client.account(account_id)
            if etype == "Campaign"
            else need_id(parent_id, "parent_campaign_id")
        )
        return client.request(
            "POST",
            f"{CM}/NegativeKeywords/QueryByEntityIds",
            body={"EntityIds": ids, "EntityType": etype, "ParentEntityId": parent},
            account_id=account_id,
            customer_id=customer_id,
            read_only=True,
        )

    @mcp.tool()
    def microsoft_ads_list_negative_keywords(
        entity_type: str,
        entity_ids: list[str],
        parent_campaign_id: str | None = None,
        account_id: str | None = None,
        customer_id: str | None = None,
    ) -> dict[str, Any]:
        """List negative keywords attached directly to campaigns or ad groups.

        entity_type: 'Campaign' or 'AdGroup'. For ad groups also pass
        parent_campaign_id. Shared negative keyword lists are not included; use
        microsoft_ads_read_request on /CampaignManagement/v13/SharedEntities/QueryByAccountId.
        """
        out = fetch_negatives(entity_type, entity_ids, parent_campaign_id, account_id, customer_id)
        return with_errors(out)

    @mcp.tool()
    def microsoft_ads_add_negative_keywords(
        entity_type: str,
        entity_ids: list[str],
        keywords: list[str],
        match_type: str = "Phrase",
        account_id: str | None = None,
        customer_id: str | None = None,
        confirm: str = "",
    ) -> dict[str, Any]:
        """Add the same negative keywords to one or more campaigns or ad groups.

        entity_type: 'Campaign' or 'AdGroup'. match_type: 'Phrase' (default) or
        'Exact'. More than MICROSOFT_ADS_BULK_THRESHOLD keyword-entity pairs need
        confirm='APPLY'. Changes the live account.
        """
        etype = _entity_type(entity_type)
        ids = ids_to_strings(entity_ids)
        words = [k.strip() for k in keywords if k and k.strip()]
        if not ids or not words:
            raise ValueError("Pass at least one entity ID and one keyword.")
        mt = MATCH_TYPES.get(match_type.strip().lower())
        if mt is None:
            raise ValueError("match_type must be 'Phrase' or 'Exact'.")
        body = {
            "EntityNegativeKeywords": [
                {
                    "EntityId": eid,
                    "EntityType": etype,
                    "NegativeKeywords": [
                        {"Type": "NegativeKeyword", "Text": w, "MatchType": mt} for w in words
                    ],
                }
                for eid in ids
            ]
        }
        decision = safety.assess(client.config, count=len(ids) * len(words))
        refused = safety.refusal(client.config, decision, confirm, preview=body)
        if refused:
            return refused
        out = client.request(
            "POST",
            f"{CM}/EntityNegativeKeywords",
            body=body,
            account_id=account_id,
            customer_id=customer_id,
            op="add_negative_keywords",
        )
        return safety.annotate(with_errors(out), decision)

    @mcp.tool()
    def microsoft_ads_delete_negative_keywords(
        entity_type: str,
        entity_id: str,
        negative_keyword_ids: list[str],
        parent_campaign_id: str | None = None,
        account_id: str | None = None,
        customer_id: str | None = None,
        confirm: str = "",
    ) -> dict[str, Any]:
        """Remove negative keywords from one campaign or ad group by negative keyword ID.

        Get the IDs from microsoft_ads_list_negative_keywords. Needs
        confirm='DELETE' after the user agrees. For ad groups pass parent_campaign_id
        so the current negatives can be saved in the audit log first.
        """
        etype = _entity_type(entity_type)
        eid = need_id(entity_id, "entity_id")
        neg_ids = ids_to_strings(negative_keyword_ids)
        if not neg_ids:
            raise ValueError("Pass at least one negative keyword ID.")
        body = {
            "EntityNegativeKeywords": [
                {
                    "EntityId": eid,
                    "EntityType": etype,
                    "NegativeKeywords": [{"Type": "NegativeKeyword", "Id": n} for n in neg_ids],
                }
            ]
        }
        decision = safety.assess(client.config, count=len(neg_ids), destructive=safety.DELETE)
        refused = safety.refusal(client.config, decision, confirm, preview=body)
        if refused:
            return refused
        before = None
        if etype == "Campaign" or parent_campaign_id:
            before = client.snapshot(
                fetch_negatives, etype, [eid], parent_campaign_id, account_id, customer_id
            )
        out = client.request(
            "DELETE",
            f"{CM}/EntityNegativeKeywords",
            body=body,
            account_id=account_id,
            customer_id=customer_id,
            op="delete_negative_keywords",
            before=before,
        )
        return safety.annotate(with_errors(out), decision)
