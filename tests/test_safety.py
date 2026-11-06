"""Confirm-word guards."""

from __future__ import annotations

import dataclasses

from microsoft_ads_mcp import safety
from microsoft_ads_mcp.config import Config


def test_delete_needs_delete(config: Config) -> None:
    d = safety.assess(config, count=1, destructive=safety.DELETE)
    assert d.required == "DELETE"
    refused = safety.refusal(config, d, "", preview={"ids": ["1"]})
    assert refused and refused["refused"] and "DELETE" in refused["error"]
    assert safety.refusal(config, d, "DELETE") is None
    assert safety.refusal(config, d, "delete") is not None


def test_bulk_threshold(config: Config) -> None:
    assert safety.assess(config, count=10).required is None
    assert safety.assess(config, count=11).required == "APPLY"


def test_budget_rise_above_limit(config: Config) -> None:
    items = [{"Id": "1", "DailyBudget": 13}, {"Id": "2", "DailyBudget": 11}]
    current = [{"Id": "1", "DailyBudget": 10}, {"Id": "2", "DailyBudget": 10}]
    changes = safety.money_changes(items, current, fields=safety.CAMPAIGN_MONEY)
    d = safety.assess(config, count=2, changes=changes)
    assert d.required == "APPLY"
    assert any("rises from 10.0 to 13.0" in r for r in d.reasons)
    assert not any("for 2 " in r for r in d.reasons)
    assert d.changes[0]["change_pct"] == 30.0


def test_unknown_current_value_needs_apply(config: Config) -> None:
    changes = safety.money_changes(
        [{"Id": "1", "Bid": {"Amount": 1}}], None, fields=safety.KEYWORD_MONEY
    )
    assert safety.assess(config, count=1, changes=changes).required == "APPLY"


def test_decrease_and_small_rise_pass(config: Config) -> None:
    items = [{"Id": "1", "CpcBid": {"Amount": 0.55}}, {"Id": "2", "CpcBid": {"Amount": 0.4}}]
    current = [{"Id": "1", "CpcBid": {"Amount": 0.5}}, {"Id": "2", "CpcBid": {"Amount": 0.5}}]
    changes = safety.money_changes(items, current, fields=safety.AD_GROUP_MONEY)
    assert safety.assess(config, count=2, changes=changes).required is None


def test_caps_apply_to_creates(config: Config) -> None:
    capped = dataclasses.replace(config, max_daily_budget=50.0, max_bid=2.0)
    budget = safety.new_values([{"DailyBudget": 80}], safety.CAMPAIGN_MONEY)
    assert safety.assess(capped, count=1, changes=budget, creating=True).required == "APPLY"
    small = safety.new_values([{"DailyBudget": 20}], safety.CAMPAIGN_MONEY)
    assert safety.assess(capped, count=1, changes=small, creating=True).required is None


def test_always_reason_and_dry_run(config: Config) -> None:
    d = safety.assess(config, count=1, always="applying recommendations")
    assert d.required == "APPLY"
    dry = dataclasses.replace(config, dry_run=True)
    assert safety.refusal(dry, d, "") is None
    out = safety.annotate({"a": 1}, d)
    assert out["safety"]["required_confirm"] == "APPLY"
