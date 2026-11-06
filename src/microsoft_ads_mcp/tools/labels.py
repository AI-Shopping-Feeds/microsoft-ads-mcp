"""Labels and label associations."""

from __future__ import annotations

from typing import Any

from .. import safety
from ..client import MicrosoftAdsClient
from ._common import CM, EntitySpec, check_items, ids_to_strings, register_entity, with_errors

SPEC = EntitySpec(
    noun="labels",
    label="labels",
    resource="Labels",
    ids_key="LabelIds",
    parent="none",
    max_items=100,
    paged=True,
    list_note=" Without ids, every active label in the account is returned.",
    create_example='e.g. {"Name": "Black Friday", "ColorCode": "#0078D4", "Description": "Q4 sale"}.',
    update_example='e.g. {"Id": "555", "Name": "Black Friday 2026"}.',
)

LABEL_ENTITY_TYPES = ("Campaign", "AdGroup", "Ad", "Keyword")


def _etype(value: str) -> str:
    for t in LABEL_ENTITY_TYPES:
        if value.strip().lower().replace("_", "") == t.lower():
            return t
    raise ValueError(f"entity_type must be one of {', '.join(LABEL_ENTITY_TYPES)}.")


def register(mcp, client: MicrosoftAdsClient) -> None:
    register_entity(mcp, client, SPEC)

    @mcp.tool()
    def microsoft_ads_list_label_associations(
        entity_type: str,
        entity_ids: list[str],
        account_id: str | None = None,
        customer_id: str | None = None,
    ) -> dict[str, Any]:
        """List the labels on campaigns, ad groups, ads or keywords.

        entity_type: Campaign, AdGroup, Ad or Keyword.
        """
        ids = ids_to_strings(entity_ids)
        if not ids:
            raise ValueError("Pass at least one entity ID.")
        out = client.request(
            "POST",
            f"{CM}/LabelAssociations/QueryByEntityIds",
            body={"EntityType": _etype(entity_type), "EntityIds": ids},
            account_id=account_id,
            customer_id=customer_id,
            read_only=True,
        )
        return with_errors(out)

    def _associate(
        method, op, entity_type, associations, account_id, customer_id, confirm, destructive
    ):
        check_items(associations, "associations", 1000)
        rows = []
        for a in associations:
            eid, lid = (
                a.get("EntityId") or a.get("entity_id"),
                a.get("LabelId") or a.get("label_id"),
            )
            ids = ids_to_strings([eid, lid])
            if len(ids) != 2:
                raise ValueError("Each association needs EntityId and LabelId.")
            rows.append({"EntityId": ids[0], "LabelId": ids[1]})
        body = {"EntityType": _etype(entity_type), "LabelAssociations": rows}
        decision = safety.assess(
            client.config, count=len(rows), destructive=safety.DELETE if destructive else None
        )
        refused = safety.refusal(client.config, decision, confirm, preview=body)
        if refused:
            return refused
        out = client.request(
            method,
            f"{CM}/LabelAssociations" + ("" if destructive else "/Set"),
            body=body,
            account_id=account_id,
            customer_id=customer_id,
            op=op,
        )
        return safety.annotate(with_errors(out), decision)

    @mcp.tool()
    def microsoft_ads_set_label_associations(
        entity_type: str,
        associations: list[dict[str, Any]],
        account_id: str | None = None,
        customer_id: str | None = None,
        confirm: str = "",
    ) -> dict[str, Any]:
        """Attach labels to entities. associations: [{"EntityId": "...", "LabelId": "..."}].

        entity_type: Campaign, AdGroup, Ad or Keyword. More than
        MICROSOFT_ADS_BULK_THRESHOLD associations need confirm='APPLY'.
        """
        return _associate(
            "POST",
            "set_label_associations",
            entity_type,
            associations,
            account_id,
            customer_id,
            confirm,
            False,
        )

    @mcp.tool()
    def microsoft_ads_delete_label_associations(
        entity_type: str,
        associations: list[dict[str, Any]],
        account_id: str | None = None,
        customer_id: str | None = None,
        confirm: str = "",
    ) -> dict[str, Any]:
        """Remove labels from entities. associations: [{"EntityId": "...", "LabelId": "..."}].

        Needs confirm='DELETE' after the user agrees. The labels themselves stay.
        """
        return _associate(
            "DELETE",
            "delete_label_associations",
            entity_type,
            associations,
            account_id,
            customer_id,
            confirm,
            True,
        )
