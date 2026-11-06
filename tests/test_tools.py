"""Entity and helper tools through the real server (fake auth, mocked HTTP)."""

from __future__ import annotations

import httpx
import pytest
import respx

from microsoft_ads_mcp.config import Config
from microsoft_ads_mcp.tools.ads import build_rsa
from microsoft_ads_mcp.tools.request import classify

from .conftest import (
    ACCOUNT,
    ADINSIGHT,
    CAMPAIGN,
    audit_entries,
    body_of,
    call,
    error_text,
    payload,
)

pytestmark = pytest.mark.usefixtures("patch_auth")


@respx.mock
async def test_list_campaigns_by_account(config: Config) -> None:
    route = respx.post(f"{CAMPAIGN}/Campaigns/QueryByAccountId").mock(
        return_value=httpx.Response(200, json={"Campaigns": [{"Id": "1"}, None, {"Id": "2"}]})
    )
    out = payload(await call(config, "microsoft_ads_list_campaigns", {"max_results": 1}))
    assert out["count"] == 1 and out["truncated"] is True
    body = body_of(route)
    assert body["AccountId"] == ACCOUNT
    assert body["CampaignType"] == "Search, Shopping, Audience, PerformanceMax, Hotel, App"


@respx.mock
async def test_list_campaigns_by_ids_with_extra(config: Config) -> None:
    route = respx.post(f"{CAMPAIGN}/Campaigns/QueryByIds").mock(
        return_value=httpx.Response(200, json={"Campaigns": [{"Id": "5"}]})
    )
    await call(
        config,
        "microsoft_ads_list_campaigns",
        {"ids": ["5"], "extra": {"CampaignType": "PerformanceMax"}},
    )
    assert body_of(route) == {
        "AccountId": ACCOUNT,
        "CampaignIds": ["5"],
        "CampaignType": "PerformanceMax",
    }


@respx.mock
async def test_create_campaigns_defaults_to_paused(config: Config, tmp_audit_log) -> None:
    route = respx.post(f"{CAMPAIGN}/Campaigns").mock(
        return_value=httpx.Response(200, json={"CampaignIds": ["9"], "PartialErrors": []})
    )
    out = payload(
        await call(
            config,
            "microsoft_ads_create_campaigns",
            {"items": [{"Name": "Brand", "DailyBudget": 10, "BudgetType": "DailyBudgetStandard"}]},
        )
    )
    assert out["CampaignIds"] == ["9"]
    assert body_of(route)["Campaigns"][0]["Status"] == "Paused"
    assert audit_entries(tmp_audit_log)[0]["op"] == "create_campaigns"


@respx.mock
async def test_partial_errors_are_surfaced(config: Config) -> None:
    respx.post(f"{CAMPAIGN}/Campaigns").mock(
        return_value=httpx.Response(
            200,
            json={
                "CampaignIds": [None],
                "PartialErrors": [
                    {"Code": 1, "ErrorCode": "CampaignNameInvalid", "Index": 0, "Message": "m"}
                ],
            },
        )
    )
    out = payload(await call(config, "microsoft_ads_create_campaigns", {"items": [{"Name": ""}]}))
    assert out["partial_error_count"] == 1
    assert out["partial_error_summary"][0]["ErrorCode"] == "CampaignNameInvalid"


@respx.mock
async def test_budget_rise_is_refused_then_applied(config: Config, tmp_audit_log) -> None:
    respx.post(f"{CAMPAIGN}/Campaigns/QueryByIds").mock(
        return_value=httpx.Response(200, json={"Campaigns": [{"Id": "1", "DailyBudget": 10}]})
    )
    put = respx.put(f"{CAMPAIGN}/Campaigns").mock(return_value=httpx.Response(200, json={}))
    args = {"items": [{"Id": "1", "DailyBudget": 15}]}
    refused = payload(await call(config, "microsoft_ads_update_campaigns", args))
    assert refused["refused"] is True and refused["required_confirm"] == "APPLY"
    assert not put.called
    out = payload(
        await call(config, "microsoft_ads_update_campaigns", {**args, "confirm": "APPLY"})
    )
    assert out["safety"]["money_changes"][0]["change_pct"] == 50.0
    assert audit_entries(tmp_audit_log)[0]["before"] == [{"Id": "1", "DailyBudget": 10}]


@respx.mock
async def test_small_bid_change_needs_no_confirm(config: Config) -> None:
    respx.post(f"{CAMPAIGN}/Keywords/QueryByIds").mock(
        return_value=httpx.Response(200, json={"Keywords": [{"Id": "7", "Bid": {"Amount": 1.0}}]})
    )
    put = respx.put(f"{CAMPAIGN}/Keywords").mock(return_value=httpx.Response(200, json={}))
    await call(
        config,
        "microsoft_ads_update_keywords",
        {"ad_group_id": "33", "items": [{"Id": "7", "Bid": {"Amount": 1.1}}]},
    )
    assert body_of(put) == {"AdGroupId": "33", "Keywords": [{"Id": "7", "Bid": {"Amount": 1.1}}]}


@respx.mock
async def test_delete_needs_delete_word(config: Config) -> None:
    respx.post(f"{CAMPAIGN}/AdGroups/QueryByIds").mock(
        return_value=httpx.Response(200, json={"AdGroups": [{"Id": "4"}]})
    )
    delete = respx.delete(f"{CAMPAIGN}/AdGroups").mock(return_value=httpx.Response(200, json={}))
    args = {"campaign_id": "12", "ids": ["4"]}
    assert payload(await call(config, "microsoft_ads_delete_ad_groups", args))["refused"] is True
    await call(config, "microsoft_ads_delete_ad_groups", {**args, "confirm": "DELETE"})
    assert body_of(delete) == {"CampaignId": "12", "AdGroupIds": ["4"]}


async def test_dry_run_returns_preview(config: Config, tmp_audit_log) -> None:
    with respx.mock(assert_all_called=False) as router:
        router.post(f"{CAMPAIGN}/Ads/QueryByIds").mock(
            return_value=httpx.Response(200, json={"Ads": []})
        )
        result = await call(
            config,
            "microsoft_ads_delete_ads",
            {"ad_group_id": "3", "ids": ["1"]},
            dry_run=True,
        )
    out = payload(result)
    assert out["_dry_run"] is True
    assert out["safety"]["required_confirm"] == "DELETE"
    assert audit_entries(tmp_audit_log)[0]["dry_run"] is True


async def test_ads_need_a_type(config: Config) -> None:
    result = await call(
        config, "microsoft_ads_create_ads", {"ad_group_id": "3", "items": [{"FinalUrls": []}]}
    )
    assert "Type" in error_text(result)


def test_build_rsa_checks_lengths() -> None:
    ad = build_rsa(
        headlines=["One", "Two", "Three"],
        descriptions=["Desc one", "Desc two"],
        final_urls=["https://example.com"],
        pins={"One": "Headline1"},
        path1="shoes",
    )
    assert ad["Type"] == "ResponsiveSearch"
    assert ad["Headlines"][0] == {
        "Asset": {"Type": "TextAsset", "Text": "One"},
        "PinnedField": "Headline1",
    }
    with pytest.raises(ValueError) as ei:
        build_rsa(headlines=["x" * 31, "a"], descriptions=["d"], final_urls=["ftp://x"])
    msg = str(ei.value)
    assert (
        "3-15 headlines" in msg and "over 30" in msg and "2-4 descriptions" in msg and "http" in msg
    )


@respx.mock
async def test_create_rsa_posts_ad(config: Config) -> None:
    route = respx.post(f"{CAMPAIGN}/Ads").mock(
        return_value=httpx.Response(200, json={"AdIds": ["1"]})
    )
    await call(
        config,
        "microsoft_ads_create_responsive_search_ad",
        {
            "ad_group_id": "3",
            "headlines": ["A", "B", "C"],
            "descriptions": ["D one", "D two"],
            "final_urls": ["https://example.com"],
        },
    )
    body = body_of(route)
    assert body["AdGroupId"] == "3" and body["Ads"][0]["Type"] == "ResponsiveSearch"


@respx.mock
async def test_add_negative_keywords(config: Config) -> None:
    route = respx.post(f"{CAMPAIGN}/EntityNegativeKeywords").mock(
        return_value=httpx.Response(200, json={"NegativeKeywordIds": []})
    )
    await call(
        config,
        "microsoft_ads_add_negative_keywords",
        {"entity_type": "campaign", "entity_ids": ["1", "2"], "keywords": ["free", "cheap"]},
    )
    body = body_of(route)
    assert len(body["EntityNegativeKeywords"]) == 2
    neg = body["EntityNegativeKeywords"][0]
    assert neg["EntityType"] == "Campaign"
    assert neg["NegativeKeywords"][0] == {
        "Type": "NegativeKeyword",
        "Text": "free",
        "MatchType": "Phrase",
    }


@respx.mock
async def test_set_status_reads_types_and_guards_enabling(config: Config) -> None:
    respx.post(f"{CAMPAIGN}/Campaigns/QueryByIds").mock(
        return_value=httpx.Response(200, json={"Campaigns": [{"Id": "1", "Status": "Paused"}]})
    )
    put = respx.put(f"{CAMPAIGN}/Campaigns").mock(return_value=httpx.Response(200, json={}))
    args = {"entity": "campaigns", "ids": ["1"], "status": "active"}
    refused = payload(await call(config, "microsoft_ads_set_status", args))
    assert refused["required_confirm"] == "APPLY"
    out = payload(await call(config, "microsoft_ads_set_status", {**args, "confirm": "APPLY"}))
    assert out["changes"] == [{"id": "1", "from": "Paused", "to": "Active"}]
    assert body_of(put) == {"Campaigns": [{"Id": "1", "Status": "Active"}], "AccountId": ACCOUNT}

    respx.post(f"{CAMPAIGN}/Ads/QueryByIds").mock(
        return_value=httpx.Response(200, json={"Ads": [{"Id": "8", "Type": "ResponsiveSearch"}]})
    )
    ads_put = respx.put(f"{CAMPAIGN}/Ads").mock(return_value=httpx.Response(200, json={}))
    await call(
        config,
        "microsoft_ads_set_status",
        {"entity": "ads", "ids": ["8"], "status": "Paused", "parent_id": "3"},
    )
    assert body_of(ads_put)["Ads"] == [{"Id": "8", "Status": "Paused", "Type": "ResponsiveSearch"}]


@respx.mock
async def test_adjust_bids(config: Config) -> None:
    respx.post(f"{CAMPAIGN}/Keywords/QueryByIds").mock(
        return_value=httpx.Response(
            200,
            json={"Keywords": [{"Id": "1", "Bid": {"Amount": 1.0}}, {"Id": "2", "Bid": None}]},
        )
    )
    put = respx.put(f"{CAMPAIGN}/Keywords").mock(return_value=httpx.Response(200, json={}))
    out = payload(
        await call(
            config,
            "microsoft_ads_adjust_bids",
            {"entity": "keywords", "parent_id": "3", "ids": ["1", "2"], "percent": -10},
        )
    )
    assert out["changed"] == 1 and out["skipped"][0]["id"] == "2"
    assert body_of(put)["Keywords"] == [{"Id": "1", "Bid": {"Amount": 0.9}}]
    rise = payload(
        await call(
            config,
            "microsoft_ads_adjust_bids",
            {"entity": "keywords", "parent_id": "3", "ids": ["1"], "percent": 50},
        )
    )
    assert rise["refused"] is True


@respx.mock
async def test_keyword_ideas_body(config: Config) -> None:
    route = respx.post(f"{ADINSIGHT}/KeywordIdeas/Query").mock(
        return_value=httpx.Response(
            200, json={"KeywordIdeas": [{"Keyword": "a"}, {"Keyword": "b"}]}
        )
    )
    out = payload(
        await call(
            config,
            "microsoft_ads_keyword_ideas",
            {"location_ids": ["100"], "queries": ["running shoes"], "max_results": 1},
        )
    )
    assert out["count"] == 2 and out["truncated"] is True
    types = [p["Type"] for p in body_of(route)["SearchParameters"]]
    assert types == [
        "LocationSearchParameter",
        "LanguageSearchParameter",
        "NetworkSearchParameter",
        "QuerySearchParameter",
    ]


async def test_apply_recommendations_always_needs_apply(config: Config) -> None:
    out = payload(
        await call(
            config,
            "microsoft_ads_apply_recommendations",
            {"items": [{"RecommendationId": "1", "RecommendationType": "BudgetOpportunity"}]},
        )
    )
    assert out["refused"] is True and out["required_confirm"] == "APPLY"


def test_classify_escape_hatch() -> None:
    assert classify("post", "/CampaignManagement/v13/Campaigns/QueryByIds")[2] is True
    assert classify("POST", "/CustomerManagement/v13/Accounts/Search")[2] is True
    assert classify("POST", "/Reporting/v13/GenerateReport/Submit")[2] is True
    assert classify("POST", "/Bulk/v13/Campaigns/DownloadByAccountIds")[2] is True
    assert classify("POST", "/CampaignManagement/v13/Campaigns")[2] is False
    assert classify("POST", "/CampaignManagement/v13/LabelAssociations/Set")[2] is False
    assert classify("PUT", "/CampaignManagement/v13/Campaigns/QueryByIds")[2] is False
    with pytest.raises(ValueError):
        classify("GET", "/CampaignManagement/v13/Campaigns")
    with pytest.raises(ValueError):
        classify("POST", "https://evil.example.com/CampaignManagement/v13/x")


@respx.mock
async def test_read_request_refuses_writes_and_request_needs_apply(config: Config) -> None:
    result = await call(
        config, "microsoft_ads_read_request", {"path": "/CampaignManagement/v13/Campaigns"}
    )
    assert "microsoft_ads_request" in error_text(result)
    refused = payload(
        await call(
            config,
            "microsoft_ads_request",
            {
                "method": "DELETE",
                "path": "/CampaignManagement/v13/Labels",
                "body": {"LabelIds": ["1"]},
            },
        )
    )
    assert refused["required_confirm"] == "APPLY"
    route = respx.post(f"{CAMPAIGN}/SharedEntities/QueryByAccountId").mock(
        return_value=httpx.Response(200, json={"SharedEntities": []})
    )
    await call(
        config,
        "microsoft_ads_read_request",
        {
            "path": "/CampaignManagement/v13/SharedEntities/QueryByAccountId",
            "body": {"SharedEntityType": "NegativeKeywordList"},
        },
    )
    assert route.called
