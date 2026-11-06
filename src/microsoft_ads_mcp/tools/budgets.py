"""Shared budgets and portfolio bid strategies."""

from __future__ import annotations

from .. import safety
from ..client import MicrosoftAdsClient
from ._common import EntitySpec, register_entity

BUDGETS = EntitySpec(
    noun="budgets",
    label="shared budgets",
    resource="Budgets",
    ids_key="BudgetIds",
    parent="none",
    max_items=100,
    money=safety.BUDGET_MONEY,
    list_note=" Without ids, every shared budget in the account is returned.",
    create_example=(
        'e.g. {"Name": "UK shared", "Amount": 50, "BudgetType": "DailyBudgetStandard"}. '
        "Attach it to campaigns by setting their BudgetId."
    ),
    update_example='e.g. {"Id": "333", "Amount": 60}. Amount rises are checked against the current value.',
)

BID_STRATEGIES = EntitySpec(
    noun="bid_strategies",
    label="portfolio bid strategies",
    resource="BidStrategies",
    ids_key="BidStrategyIds",
    parent="none",
    max_items=100,
    money=safety.BID_STRATEGY_MONEY,
    list_note=" Without ids, every portfolio bid strategy in the account is returned.",
    create_example=(
        'e.g. {"Name": "Portfolio tCPA", "AssociatedCampaignType": "Search", "BiddingScheme": '
        '{"Type": "TargetCpaBiddingScheme", "TargetCpa": 12}}. Attach campaigns by setting '
        "their BidStrategyId."
    ),
    update_example='e.g. {"Id": "444", "BiddingScheme": {"Type": "TargetCpaBiddingScheme", "TargetCpa": 10}}.',
)


def register(mcp, client: MicrosoftAdsClient) -> None:
    register_entity(mcp, client, BUDGETS)
    register_entity(mcp, client, BID_STRATEGIES)
