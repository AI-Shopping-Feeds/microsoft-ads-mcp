"""Ad Insight: keyword ideas, traffic and bid estimates, budget opportunities, recommendations."""

from __future__ import annotations

from typing import Any

from .. import safety
from ..client import MicrosoftAdsClient
from ._common import check_items, ids_to_strings, need_id, with_errors

AI = "/AdInsight/v13"
DEFAULT_NETWORK = "OwnedAndOperatedAndSyndicatedSearch"
DEFAULT_ATTRIBUTES = [
    "Keyword",
    "Competition",
    "MonthlySearchCounts",
    "SuggestedBid",
    "AdImpressionShare",
    "Relevance",
    "Source",
    "AdGroupId",
    "AdGroupName",
]
MATCH_TYPES = {"exact": "Exact", "phrase": "Phrase", "broad": "Broad"}


def _match(value: str) -> str:
    mt = MATCH_TYPES.get(value.strip().lower())
    if mt is None:
        raise ValueError("match_type must be Exact, Phrase or Broad.")
    return mt


def _ymd(value: str) -> dict[str, int]:
    y, m, d = (int(p) for p in value.split("-"))
    return {"Year": y, "Month": m, "Day": d}


def register(mcp, client: MicrosoftAdsClient) -> None:
    def call(path: str, body: dict[str, Any], account_id: str | None) -> Any:
        return client.request(
            "POST", f"{AI}/{path}", body=body, account_id=account_id, read_only=True
        )

    @mcp.tool()
    def microsoft_ads_keyword_ideas(
        location_ids: list[str],
        queries: list[str] | None = None,
        url: str | None = None,
        category_id: str | None = None,
        language: str = "English",
        network: str = DEFAULT_NETWORK,
        expand_ideas: bool = True,
        start_date: str | None = None,
        end_date: str | None = None,
        idea_attributes: list[str] | None = None,
        max_results: int = 200,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """Get keyword ideas with monthly searches, competition and suggested bids.

        Pass at least one of queries (seed keywords), url (a landing page) or
        category_id. location_ids are Microsoft location IDs (from the geographic
        locations file, see microsoft_ads_read_request on
        /CampaignManagement/v13/GeoLocationsFileUrl/Query). expand_ideas=False returns
        stats for the queries only. start_date/end_date (YYYY-MM-DD) bound the monthly
        search history. Returns at most max_results ideas.
        """
        if not (queries or url or category_id):
            raise ValueError("Pass queries, url or category_id.")
        locs = ids_to_strings(location_ids)
        if not locs:
            raise ValueError("Pass at least one location ID.")
        params: list[dict[str, Any]] = [
            {
                "Type": "LocationSearchParameter",
                "Locations": [{"Type": "LocationCriterion", "LocationId": loc} for loc in locs],
            },
            {
                "Type": "LanguageSearchParameter",
                "Languages": [{"Type": "LanguageCriterion", "Language": language}],
            },
            {
                "Type": "NetworkSearchParameter",
                "Network": {"Type": "NetworkCriterion", "Network": network},
            },
        ]
        if queries:
            params.append({"Type": "QuerySearchParameter", "Queries": list(queries)})
        if url:
            params.append({"Type": "UrlSearchParameter", "Url": url})
        if category_id:
            params.append(
                {
                    "Type": "CategorySearchParameter",
                    "CategoryId": need_id(category_id, "category_id"),
                }
            )
        if start_date and end_date:
            params.append(
                {
                    "Type": "DateRangeSearchParameter",
                    "StartDate": _ymd(start_date),
                    "EndDate": _ymd(end_date),
                }
            )
        out = call(
            "KeywordIdeas/Query",
            {
                "ExpandIdeas": expand_ideas,
                "IdeaAttributes": idea_attributes or DEFAULT_ATTRIBUTES,
                "SearchParameters": params,
            },
            account_id,
        )
        ideas = [i for i in (out.get("KeywordIdeas") or []) if i]
        return {
            "count": len(ideas),
            "keyword_ideas": ideas[: max(0, max_results)],
            "truncated": len(ideas) > max_results,
        }

    @mcp.tool()
    def microsoft_ads_keyword_traffic_estimates(
        keywords: list[str],
        max_cpc: float,
        location_ids: list[str],
        match_type: str = "Phrase",
        language: str = "English",
        daily_budget: float | None = None,
        network: str = DEFAULT_NETWORK,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """Estimate weekly impressions, clicks, cost, CTR and average CPC for keywords
        at a given max CPC, in the given locations and language."""
        words = [k.strip() for k in keywords if k and k.strip()]
        if not words:
            raise ValueError("Pass at least one keyword.")
        mt = _match(match_type)
        criteria: list[dict[str, Any]] = [{"Type": "LanguageCriterion", "Language": language}]
        criteria += [
            {"Type": "LocationCriterion", "LocationId": loc} for loc in ids_to_strings(location_ids)
        ]
        criteria.append({"Type": "NetworkCriterion", "Network": network})
        estimator: dict[str, Any] = {
            "Criteria": criteria,
            "AdGroupEstimators": [
                {
                    "MaxCpc": max_cpc,
                    "KeywordEstimators": [
                        {"Keyword": {"Text": w, "MatchType": mt}, "MaxCpc": max_cpc} for w in words
                    ],
                }
            ],
        }
        if daily_budget is not None:
            estimator["DailyBudget"] = daily_budget
        return call(
            "KeywordTrafficEstimates/query", {"CampaignEstimators": [estimator]}, account_id
        )

    @mcp.tool()
    def microsoft_ads_estimated_bids(
        keywords: list[str],
        match_type: str = "Exact",
        target_position: str = "MainLine",
        location_ids: list[str] | None = None,
        language: str | None = None,
        currency_code: str | None = None,
        campaign_id: str | None = None,
        ad_group_id: str | None = None,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """Estimate the bid needed to reach a position (MainLine1, MainLine or FirstPage)
        for keywords, with estimated clicks, impressions and cost."""
        words = [k.strip() for k in keywords if k and k.strip()]
        if not words:
            raise ValueError("Pass at least one keyword.")
        mt = _match(match_type)
        body: dict[str, Any] = {
            "Keywords": [{"Text": w, "MatchType": mt} for w in words],
            "TargetPositionForAds": target_position,
        }
        if location_ids:
            body["LocationIds"] = ids_to_strings(location_ids)
        if language:
            body["Language"] = language
        if currency_code:
            body["CurrencyCode"] = currency_code
        if campaign_id:
            body["CampaignId"] = need_id(campaign_id, "campaign_id")
        if ad_group_id:
            body["AdGroupId"] = need_id(ad_group_id, "ad_group_id")
        return call("EstimatedBid/queryByKeywords", body, account_id)

    @mcp.tool()
    def microsoft_ads_budget_opportunities(
        campaign_id: str, account_id: str | None = None
    ) -> dict[str, Any]:
        """Get Microsoft's budget suggestions for a campaign that is limited by budget,
        with the estimated extra impressions and clicks."""
        return call(
            "BudgetOpportunities/query",
            {"CampaignId": need_id(campaign_id, "campaign_id")},
            account_id,
        )

    @mcp.tool()
    def microsoft_ads_list_recommendations(
        campaign_id: str | None = None,
        ad_group_id: str | None = None,
        recommendation_type: str | None = None,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """List Microsoft's recommendations for the account (or one campaign or ad group),
        optionally of one recommendation_type. Review them with the user before applying."""
        body: dict[str, Any] = {}
        if campaign_id:
            body["CampaignId"] = need_id(campaign_id, "campaign_id")
        if ad_group_id:
            body["AdGroupId"] = need_id(ad_group_id, "ad_group_id")
        if recommendation_type:
            body["RecommendationType"] = recommendation_type
        return with_errors(call("Recommendations/query", body, account_id))

    def act(path, op, items, account_id, confirm, always):
        check_items(items, "recommendations", 100)
        entities = []
        for i, it in enumerate(items):
            rid = it.get("RecommendationId") or it.get("recommendation_id")
            rtype = it.get("RecommendationType") or it.get("recommendation_type")
            if not rid or not rtype:
                raise ValueError(f"items[{i}] needs RecommendationId and RecommendationType.")
            entities.append({"RecommendationId": str(rid), "RecommendationType": rtype})
        decision = safety.assess(client.config, count=len(entities), always=always)
        body = {"Entities": entities}
        refused = safety.refusal(client.config, decision, confirm, preview=body)
        if refused:
            return refused
        out = client.request(
            "POST", f"{AI}/Recommendations/{path}", body=body, account_id=account_id, op=op
        )
        return safety.annotate(with_errors(out), decision)

    @mcp.tool()
    def microsoft_ads_apply_recommendations(
        items: list[dict[str, Any]],
        account_id: str | None = None,
        confirm: str = "",
    ) -> dict[str, Any]:
        """Apply recommendations from microsoft_ads_list_recommendations.

        items: [{"RecommendationId": "...", "RecommendationType": "..."}]. Applying can
        raise budgets and bids or add keywords, and this server can't check the effect,
        so it always needs confirm='APPLY' after the user has seen each recommendation.
        """
        return act(
            "apply",
            "apply_recommendations",
            items,
            account_id,
            confirm,
            "applying recommendations can change budgets, bids and targeting",
        )

    @mcp.tool()
    def microsoft_ads_dismiss_recommendations(
        items: list[dict[str, Any]],
        account_id: str | None = None,
        confirm: str = "",
    ) -> dict[str, Any]:
        """Dismiss recommendations so they stop showing.

        items: [{"RecommendationId": "...", "RecommendationType": "..."}]. Large batches
        need confirm='APPLY'.
        """
        return act("dismiss", "dismiss_recommendations", items, account_id, confirm, None)
