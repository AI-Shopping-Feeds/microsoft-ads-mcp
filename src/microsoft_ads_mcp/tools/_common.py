"""Shared building blocks for the Campaign Management entity tools.

Campaign Management v13 REST follows one pattern for most entities:

* add:    POST   /CampaignManagement/v13/<Entities>          {<Parent>Id, <Entities>: [...]}
* update: PUT    /CampaignManagement/v13/<Entities>          {<Parent>Id, <Entities>: [...]}
* delete: DELETE /CampaignManagement/v13/<Entities>          {<Parent>Id, <Entity>Ids: [...]}
* get:    POST   /CampaignManagement/v13/<Entities>/QueryByIds (or QueryBy<Parent>Id)

`register_entity()` generates list, create, update and delete tools for one
entity from a small spec, with the same guards, before-snapshots and audit
trail for every entity. Responses keep Microsoft's field names; batch
operations can partly succeed, so results include any PartialErrors.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from .. import safety
from ..client import MicrosoftAdsClient, error_details

CM = "/CampaignManagement/v13"

# parent kind -> (request body key, tool argument name)
PARENTS: dict[str, tuple[str | None, str | None]] = {
    "account": ("AccountId", "account_id"),
    "campaign": ("CampaignId", "campaign_id"),
    "ad_group": ("AdGroupId", "ad_group_id"),
    "none": (None, None),
}


def ids_to_strings(ids: Sequence[Any] | None) -> list[str]:
    out = [str(i).strip() for i in (ids or []) if str(i).strip()]
    bad = [i for i in out if not i.isdigit()]
    if bad:
        raise ValueError(f"IDs must be numeric; got {bad[:5]}.")
    return out


def need_id(value: Any, name: str) -> str:
    text = str(value).strip() if value not in (None, "") else ""
    if not text:
        raise ValueError(f"{name} is required.")
    if not text.isdigit():
        raise ValueError(f"{name} must be a numeric ID, got '{text}'.")
    return text


def check_items(items: list[dict[str, Any]], what: str, max_items: int) -> None:
    if not items:
        raise ValueError(f"Pass at least one {what}.")
    if len(items) > max_items:
        raise ValueError(f"At most {max_items} {what} per call; got {len(items)}.")
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"{what}[{i}] must be an object.")


def require_ids(items: list[dict[str, Any]], id_field: str = "Id") -> list[str]:
    missing = [i for i, it in enumerate(items) if not it.get(id_field)]
    if missing:
        raise ValueError(f"Every item needs {id_field}; missing at index {missing[:10]}.")
    return ids_to_strings([it[id_field] for it in items])


def with_errors(out: Any) -> Any:
    """Surface PartialErrors (batch items that failed) at the top of a result."""
    if not isinstance(out, dict):
        return out
    partial = out.get("PartialErrors") or out.get("NestedPartialErrors")
    if partial:
        details = error_details(partial, limit=50)
        return {
            **out,
            "partial_error_count": len(partial) if isinstance(partial, list) else len(details),
            "partial_error_summary": details,
        }
    return out


@dataclass(frozen=True)
class EntitySpec:
    """One Campaign Management entity with add/update/delete/get operations."""

    noun: str  # tool noun, e.g. "ad_groups"
    label: str  # human label, e.g. "ad groups"
    resource: str  # path segment and items key, e.g. "AdGroups"
    ids_key: str  # e.g. "AdGroupIds"
    parent: str  # "account", "campaign", "ad_group" or "none"
    list_op: str | None = None  # e.g. "QueryByCampaignId"; None lists via QueryByIds with no IDs
    max_items: int = 100
    money: tuple[tuple[str, tuple[str, ...]], ...] = ()
    list_defaults: dict[str, Any] = field(default_factory=dict)
    create_defaults: dict[str, Any] = field(default_factory=dict)
    create_example: str = ""
    update_example: str = ""
    list_note: str = ""
    needs_type: bool = False
    paged: bool = False  # QueryByIds takes PageInfo (labels)

    @property
    def path(self) -> str:
        return f"{CM}/{self.resource}"


def _parent_body(
    client: MicrosoftAdsClient, spec: EntitySpec, parent_id: Any, account_id: Any
) -> dict[str, Any]:
    key, arg = PARENTS[spec.parent]
    if key is None:
        return {}
    if spec.parent == "account":
        return {key: client.account(account_id)}
    return {key: need_id(parent_id, str(arg))}


def fetch(
    client: MicrosoftAdsClient,
    spec: EntitySpec,
    *,
    parent_id: Any = None,
    ids: Sequence[Any] | None = None,
    extra: dict[str, Any] | None = None,
    account_id: Any = None,
    customer_id: Any = None,
    max_results: int = 1000,
) -> tuple[list[Any], bool, Any]:
    """Get entities by ID, or all of them under the parent. Returns (items, truncated, errors)."""
    id_list = ids_to_strings(ids)
    body: dict[str, Any] = {**spec.list_defaults, **(extra or {})}
    body.update(_parent_body(client, spec, parent_id, account_id))
    if id_list:
        body[spec.ids_key] = id_list
        path = f"{spec.path}/QueryByIds"
    elif spec.list_op:
        path = f"{spec.path}/{spec.list_op}"
    else:
        path = f"{spec.path}/QueryByIds"
    items: list[Any] = []
    errors: Any = None
    index = 0
    while True:
        if spec.paged:
            body["PageInfo"] = {"Index": index, "Size": 1000}
        out = client.request(
            "POST",
            path,
            body=body,
            account_id=account_id,
            customer_id=customer_id,
            read_only=True,
        )
        page = [i for i in (out.get(spec.resource) or []) if i is not None]
        items.extend(page)
        errors = errors or out.get("PartialErrors")
        if not spec.paged or len(page) < 1000 or len(items) >= max_results:
            break
        index += 1
    return items[: max(0, max_results)], len(items) > max_results, errors


def register_entity(
    mcp, client: MicrosoftAdsClient, spec: EntitySpec
) -> dict[str, Callable[..., Any]]:
    """Register microsoft_ads_{list,create,update,delete}_<noun>; returns the functions by verb."""
    _, arg = PARENTS[spec.parent]
    parent_note = f" {arg} is required." if spec.parent in ("campaign", "ad_group") else ""
    scope_note = (
        " account_id and customer_id default to MICROSOFT_ADS_ACCOUNT_ID and "
        "MICROSOFT_ADS_CUSTOMER_ID (the customer is looked up from the account if unset)."
    )

    def do_list(parent_id, ids, extra, max_results, account_id, customer_id):
        items, truncated, errors = fetch(
            client,
            spec,
            parent_id=parent_id,
            ids=ids,
            extra=extra,
            account_id=account_id,
            customer_id=customer_id,
            max_results=max_results,
        )
        out: dict[str, Any] = {spec.resource: items, "count": len(items), "truncated": truncated}
        if errors:
            out["PartialErrors"] = errors
        return with_errors(out)

    def check_types(items):
        if spec.needs_type:
            missing = [i for i, it in enumerate(items) if not it.get("Type")]
            if missing:
                raise ValueError(f"Every item needs a Type; missing at index {missing[:10]}.")

    def do_create(items, parent_id, account_id, customer_id, confirm):
        check_items(items, spec.label, spec.max_items)
        check_types(items)
        payload = [{**spec.create_defaults, **it} for it in items]
        decision = safety.assess(
            client.config,
            count=len(payload),
            changes=safety.new_values(payload, spec.money),
            creating=True,
        )
        body = {**_parent_body(client, spec, parent_id, account_id), spec.resource: payload}
        refused = safety.refusal(client.config, decision, confirm, preview=body)
        if refused:
            return refused
        out = client.request(
            "POST",
            spec.path,
            body=body,
            account_id=account_id,
            customer_id=customer_id,
            op=f"create_{spec.noun}",
        )
        return safety.annotate(with_errors(out), decision)

    def do_update(items, parent_id, account_id, customer_id, confirm):
        check_items(items, spec.label, spec.max_items)
        check_types(items)
        ids = require_ids(items)
        before = client.snapshot(
            fetch,
            client,
            spec,
            parent_id=parent_id,
            ids=ids,
            account_id=account_id,
            customer_id=customer_id,
            max_results=len(ids),
        )
        current = before[0] if before else None
        decision = safety.assess(
            client.config,
            count=len(items),
            changes=safety.money_changes(items, current, fields=spec.money),
        )
        body = {**_parent_body(client, spec, parent_id, account_id), spec.resource: items}
        refused = safety.refusal(client.config, decision, confirm, preview=body)
        if refused:
            return refused
        out = client.request(
            "PUT",
            spec.path,
            body=body,
            account_id=account_id,
            customer_id=customer_id,
            op=f"update_{spec.noun}",
            before=current,
        )
        return safety.annotate(with_errors(out), decision)

    def do_delete(ids, parent_id, account_id, customer_id, confirm):
        id_list = ids_to_strings(ids)
        if not id_list:
            raise ValueError("Pass at least one ID.")
        if len(id_list) > spec.max_items:
            raise ValueError(f"At most {spec.max_items} IDs per call.")
        decision = safety.assess(client.config, count=len(id_list), destructive=safety.DELETE)
        body = {**_parent_body(client, spec, parent_id, account_id), spec.ids_key: id_list}
        refused = safety.refusal(client.config, decision, confirm, preview=body)
        if refused:
            return refused
        before = client.snapshot(
            fetch,
            client,
            spec,
            parent_id=parent_id,
            ids=id_list,
            account_id=account_id,
            customer_id=customer_id,
            max_results=len(id_list),
        )
        out = client.request(
            "DELETE",
            spec.path,
            body=body,
            account_id=account_id,
            customer_id=customer_id,
            op=f"delete_{spec.noun}",
            before=before[0] if before else None,
        )
        return safety.annotate(with_errors(out), decision)

    list_desc = (
        f"List {spec.label}. Pass ids to get specific ones; otherwise all {spec.label} "
        f"under the parent are returned (up to max_results).{parent_note}{spec.list_note}\n\n"
        "extra is merged into the request body for other fields the API accepts, e.g. "
        '{"ReturnAdditionalFields": "..."}.' + scope_note
    )
    create_desc = (
        f"Create {spec.label} (up to {spec.max_items} per call). Changes the live account."
        f"{parent_note}\n\nitems: one object per entity, using Microsoft's field names. "
        f"{spec.create_example}\nLarge batches and values over the configured caps need "
        "confirm='APPLY'. Rehearse with dry-run first. Failed items are listed in PartialErrors."
    )
    update_desc = (
        f"Update {spec.label} (up to {spec.max_items} per call). Changes the live account."
        f"{parent_note}\n\nitems: objects with Id plus only the fields to change. "
        f"{spec.update_example}\nCurrent values are read first and kept in the audit log. "
        "Bid or budget increases above MICROSOFT_ADS_MAX_INCREASE_PCT, and large batches, "
        "need confirm='APPLY'."
    )
    delete_desc = (
        f"Delete {spec.label} by ID. Deleted entities can't be restored, so this needs "
        "confirm='DELETE' after the user agrees. To stop them temporarily, set Status to "
        f"Paused with microsoft_ads_update_{spec.noun} or microsoft_ads_set_status instead."
        f"{parent_note}"
    )
    tools: dict[str, tuple[Callable[..., Any], str]] = {}

    if spec.parent == "campaign":

        def list_c(
            campaign_id: str,
            ids: list[str] | None = None,
            extra: dict[str, Any] | None = None,
            max_results: int = 500,
            account_id: str | None = None,
            customer_id: str | None = None,
        ) -> dict[str, Any]:
            return do_list(campaign_id, ids, extra, max_results, account_id, customer_id)

        def create_c(
            campaign_id: str,
            items: list[dict[str, Any]],
            account_id: str | None = None,
            customer_id: str | None = None,
            confirm: str = "",
        ) -> dict[str, Any]:
            return do_create(items, campaign_id, account_id, customer_id, confirm)

        def update_c(
            campaign_id: str,
            items: list[dict[str, Any]],
            account_id: str | None = None,
            customer_id: str | None = None,
            confirm: str = "",
        ) -> dict[str, Any]:
            return do_update(items, campaign_id, account_id, customer_id, confirm)

        def delete_c(
            campaign_id: str,
            ids: list[str],
            account_id: str | None = None,
            customer_id: str | None = None,
            confirm: str = "",
        ) -> dict[str, Any]:
            return do_delete(ids, campaign_id, account_id, customer_id, confirm)

        tools = {
            "list": (list_c, list_desc),
            "create": (create_c, create_desc),
            "update": (update_c, update_desc),
            "delete": (delete_c, delete_desc),
        }
    elif spec.parent == "ad_group":

        def list_a(
            ad_group_id: str,
            ids: list[str] | None = None,
            extra: dict[str, Any] | None = None,
            max_results: int = 500,
            account_id: str | None = None,
            customer_id: str | None = None,
        ) -> dict[str, Any]:
            return do_list(ad_group_id, ids, extra, max_results, account_id, customer_id)

        def create_a(
            ad_group_id: str,
            items: list[dict[str, Any]],
            account_id: str | None = None,
            customer_id: str | None = None,
            confirm: str = "",
        ) -> dict[str, Any]:
            return do_create(items, ad_group_id, account_id, customer_id, confirm)

        def update_a(
            ad_group_id: str,
            items: list[dict[str, Any]],
            account_id: str | None = None,
            customer_id: str | None = None,
            confirm: str = "",
        ) -> dict[str, Any]:
            return do_update(items, ad_group_id, account_id, customer_id, confirm)

        def delete_a(
            ad_group_id: str,
            ids: list[str],
            account_id: str | None = None,
            customer_id: str | None = None,
            confirm: str = "",
        ) -> dict[str, Any]:
            return do_delete(ids, ad_group_id, account_id, customer_id, confirm)

        tools = {
            "list": (list_a, list_desc),
            "create": (create_a, create_desc),
            "update": (update_a, update_desc),
            "delete": (delete_a, delete_desc),
        }
    else:

        def list_n(
            ids: list[str] | None = None,
            extra: dict[str, Any] | None = None,
            max_results: int = 500,
            account_id: str | None = None,
            customer_id: str | None = None,
        ) -> dict[str, Any]:
            return do_list(None, ids, extra, max_results, account_id, customer_id)

        def create_n(
            items: list[dict[str, Any]],
            account_id: str | None = None,
            customer_id: str | None = None,
            confirm: str = "",
        ) -> dict[str, Any]:
            return do_create(items, None, account_id, customer_id, confirm)

        def update_n(
            items: list[dict[str, Any]],
            account_id: str | None = None,
            customer_id: str | None = None,
            confirm: str = "",
        ) -> dict[str, Any]:
            return do_update(items, None, account_id, customer_id, confirm)

        def delete_n(
            ids: list[str],
            account_id: str | None = None,
            customer_id: str | None = None,
            confirm: str = "",
        ) -> dict[str, Any]:
            return do_delete(ids, None, account_id, customer_id, confirm)

        tools = {
            "list": (list_n, list_desc),
            "create": (create_n, create_desc),
            "update": (update_n, update_desc),
            "delete": (delete_n, delete_desc),
        }

    for verb in ("list", "create", "update", "delete"):
        fn, desc = tools[verb]
        mcp.tool(name=f"microsoft_ads_{verb}_{spec.noun}", description=desc)(fn)
    return {verb: fn for verb, (fn, _) in tools.items()}
