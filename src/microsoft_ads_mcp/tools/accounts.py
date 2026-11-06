"""Customer Management: the signed-in user, customers (manager accounts) and ad accounts."""

from __future__ import annotations

from typing import Any

from ..client import MicrosoftAdsClient
from ._common import need_id

CUST = "/CustomerManagement/v13"
USER_FIELDS = ("Id", "UserName", "CustomerId", "UserLifeCycleStatus", "Lcid", "TimeStamp")
ACCOUNT_FIELDS = (
    "Id",
    "Name",
    "Number",
    "ParentCustomerId",
    "AccountLifeCycleStatus",
    "PauseReason",
    "CurrencyCode",
    "TimeZone",
    "Language",
    "AccountMode",
)
# Billing and tax details are left out of account results.
ACCOUNT_DROP = {
    "TaxCertificate",
    "TaxInformation",
    "BusinessAddress",
    "PaymentMethodId",
    "BackUpPaymentInstrumentId",
    "SoldToPaymentInstrumentId",
}


def current_user(client: MicrosoftAdsClient) -> dict[str, Any]:
    out = client.request("POST", f"{CUST}/User/Query", body={"UserId": None}, read_only=True)
    return out if isinstance(out, dict) else {}


def search_accounts(
    client: MicrosoftAdsClient, field: str, value: str, max_results: int = 1000
) -> list[dict[str, Any]]:
    accounts: list[dict[str, Any]] = []
    index = 0
    size = 100
    while len(accounts) < max_results:
        out = client.request(
            "POST",
            f"{CUST}/Accounts/Search",
            body={
                "Predicates": [{"Field": field, "Operator": "Equals", "Value": value}],
                "Ordering": [{"Field": "Name", "Order": "Ascending"}],
                "PageInfo": {"Index": index, "Size": size},
            },
            read_only=True,
        )
        page = [a for a in (out.get("Accounts") or []) if a]
        accounts.extend(page)
        if len(page) < size:
            break
        index += 1
    return accounts[:max_results]


def summarise_account(a: dict[str, Any]) -> dict[str, Any]:
    return {k: a.get(k) for k in ACCOUNT_FIELDS if a.get(k) is not None}


def register(mcp, client: MicrosoftAdsClient) -> None:
    @mcp.tool()
    def microsoft_ads_get_user() -> dict[str, Any]:
        """Show the signed-in Microsoft Advertising user and their roles per customer.

        Returns the user ID and username (no contact details) and CustomerRoles:
        which customers (manager accounts) and accounts the user can reach, and the role.
        """
        out = current_user(client)
        user = out.get("User") or {}
        return {
            "user": {k: user.get(k) for k in USER_FIELDS if user.get(k) is not None},
            "customer_roles": out.get("CustomerRoles") or [],
        }

    @mcp.tool()
    def microsoft_ads_list_accounts(
        customer_id: str | None = None,
        name_contains: str | None = None,
        max_results: int = 500,
    ) -> dict[str, Any]:
        """List the ad accounts the signed-in user can access, or the accounts of one
        customer (manager account).

        Each account has Id (use it as account_id), Name, Number (shown in the web UI),
        ParentCustomerId (the customer_id), status and currency. name_contains filters by
        name (case-insensitive).
        """
        if customer_id:
            accounts = search_accounts(
                client, "CustomerId", need_id(customer_id, "customer_id"), max_results
            )
        else:
            user = (current_user(client).get("User") or {}).get("Id")
            if not user:
                raise RuntimeError("Could not read the signed-in user's ID.")
            accounts = search_accounts(client, "UserId", str(user), max_results)
        rows = [summarise_account(a) for a in accounts]
        if name_contains:
            needle = name_contains.lower()
            rows = [r for r in rows if needle in str(r.get("Name", "")).lower()]
        return {"accounts": rows, "count": len(rows)}

    @mcp.tool()
    def microsoft_ads_get_account(account_id: str | None = None) -> dict[str, Any]:
        """Get one ad account's settings (billing and tax details are left out)."""
        aid = client.account(account_id)
        out = client.request(
            "POST", f"{CUST}/Account/Query", body={"AccountId": aid}, read_only=True
        )
        account = out.get("Account") or {}
        return {"account": {k: v for k, v in account.items() if k not in ACCOUNT_DROP}}

    @mcp.tool()
    def microsoft_ads_list_customers(name_filter: str = "", top_n: int = 100) -> dict[str, Any]:
        """List the customers (manager accounts) the signed-in user can access, optionally
        filtered by the start of the name. Use a customer's Id as customer_id."""
        out = client.request(
            "POST",
            f"{CUST}/CustomersInfo/Query",
            body={"CustomerNameFilter": name_filter, "TopN": max(1, min(top_n, 5000))},
            read_only=True,
        )
        customers = [c for c in (out.get("CustomersInfo") or []) if c]
        return {"customers": customers, "count": len(customers)}
