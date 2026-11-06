"""Campaigns (Search, Shopping, Performance Max, Audience, Hotel, App)."""

from __future__ import annotations

from .. import safety
from ..client import MicrosoftAdsClient
from ._common import EntitySpec, register_entity

DEFAULT_CAMPAIGN_TYPES = "Search, Shopping, Audience, PerformanceMax, Hotel, App"

SPEC = EntitySpec(
    noun="campaigns",
    label="campaigns",
    resource="Campaigns",
    ids_key="CampaignIds",
    parent="account",
    list_op="QueryByAccountId",
    max_items=100,
    money=safety.CAMPAIGN_MONEY,
    list_defaults={"CampaignType": DEFAULT_CAMPAIGN_TYPES},
    create_defaults={"Status": "Paused"},
    list_note=(
        " CampaignType defaults to 'Search, Shopping, Audience, PerformanceMax, Hotel, App'; "
        "narrow it with extra={'CampaignType': 'PerformanceMax'} (ObjectiveBased is also valid)."
    ),
    create_example=(
        'e.g. {"Name": "Brand - UK", "CampaignType": "Search", "BudgetType": '
        '"DailyBudgetStandard", "DailyBudget": 20, "TimeZone": '
        '"GreenwichMeanTimeDublinEdinburghLisbonLondon", "Languages": ["English"]}. '
        "Shopping and Performance Max campaigns also need a ShoppingSetting/PerformanceMaxSetting "
        "in Settings (with StoreId from Microsoft Merchant Center). New campaigns are created "
        "Paused unless Status is set."
    ),
    update_example=(
        'e.g. {"Id": "123", "DailyBudget": 25} or {"Id": "123", "Status": "Paused"}. '
        "DailyBudget rises are checked against the current value."
    ),
)


def register(mcp, client: MicrosoftAdsClient) -> None:
    register_entity(mcp, client, SPEC)
