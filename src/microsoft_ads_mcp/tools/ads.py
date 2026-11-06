"""Ads, including a helper for responsive search ads."""

from __future__ import annotations

from typing import Any

from ..client import MicrosoftAdsClient
from ._common import EntitySpec, register_entity

DEFAULT_AD_TYPES = [
    "ResponsiveSearch",
    "ResponsiveAd",
    "ExpandedText",
    "Product",
    "AppInstall",
    "DynamicSearch",
    "Hotel",
]

SPEC = EntitySpec(
    noun="ads",
    label="ads",
    resource="Ads",
    ids_key="AdIds",
    parent="ad_group",
    list_op="QueryByAdGroupId",
    max_items=50,
    needs_type=True,
    list_defaults={"AdTypes": DEFAULT_AD_TYPES},
    list_note=(
        " AdTypes defaults to every current ad type; narrow it with "
        "extra={'AdTypes': ['ResponsiveSearch']}."
    ),
    create_example=(
        'Every ad needs a Type, e.g. a responsive search ad: {"Type": "ResponsiveSearch", '
        '"FinalUrls": ["https://example.com"], "Headlines": [{"Asset": {"Type": "TextAsset", '
        '"Text": "Running shoes"}}, ...], "Descriptions": [...]} (3-15 headlines of up to 30 '
        "characters, 2-4 descriptions of up to 90). Product ads for Shopping campaigns: "
        '{"Type": "Product"}. microsoft_ads_create_responsive_search_ad builds an RSA for you.'
    ),
    update_example=(
        'Include Type, e.g. {"Id": "111", "Type": "ResponsiveSearch", "Status": "Paused"}. '
        "Replacing Headlines or Descriptions replaces the whole list."
    ),
)

MAX_HEADLINE = 30
MAX_DESCRIPTION = 90
MAX_PATH = 15


def _links(texts: list[str], pins: dict[str, str] | None) -> list[dict[str, Any]]:
    out = []
    for text in texts:
        link: dict[str, Any] = {"Asset": {"Type": "TextAsset", "Text": text}}
        if pins and pins.get(text):
            link["PinnedField"] = pins[text]
        out.append(link)
    return out


def build_rsa(
    *,
    headlines: list[str],
    descriptions: list[str],
    final_urls: list[str],
    path1: str | None = None,
    path2: str | None = None,
    pins: dict[str, str] | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Build and check a ResponsiveSearch ad body."""
    headlines = [h.strip() for h in headlines if h and h.strip()]
    descriptions = [d.strip() for d in descriptions if d and d.strip()]
    problems = []
    if not 3 <= len(headlines) <= 15:
        problems.append(f"need 3-15 headlines, got {len(headlines)}")
    if not 2 <= len(descriptions) <= 4:
        problems.append(f"need 2-4 descriptions, got {len(descriptions)}")
    problems += [
        f"headline over {MAX_HEADLINE} characters: {h!r}"
        for h in headlines
        if len(h) > MAX_HEADLINE
    ]
    problems += [
        f"description over {MAX_DESCRIPTION} characters: {d!r}"
        for d in descriptions
        if len(d) > MAX_DESCRIPTION
    ]
    problems += [
        f"{name} over {MAX_PATH} characters"
        for name, p in (("path1", path1), ("path2", path2))
        if p and len(p) > MAX_PATH
    ]
    if not final_urls or not all(str(u).startswith(("https://", "http://")) for u in final_urls):
        problems.append("final_urls must be one or more http(s) URLs")
    if problems:
        raise ValueError("Invalid responsive search ad: " + "; ".join(problems))
    ad: dict[str, Any] = {
        "Type": "ResponsiveSearch",
        "Headlines": _links(headlines, pins),
        "Descriptions": _links(descriptions, pins),
        "FinalUrls": list(final_urls),
    }
    if path1:
        ad["Path1"] = path1
    if path2:
        ad["Path2"] = path2
    if status:
        ad["Status"] = status
    return ad


def register(mcp, client: MicrosoftAdsClient) -> None:
    entity_tools = register_entity(mcp, client, SPEC)

    @mcp.tool()
    def microsoft_ads_create_responsive_search_ad(
        ad_group_id: str,
        headlines: list[str],
        descriptions: list[str],
        final_urls: list[str],
        path1: str | None = None,
        path2: str | None = None,
        pins: dict[str, str] | None = None,
        status: str | None = None,
        account_id: str | None = None,
        customer_id: str | None = None,
        confirm: str = "",
    ) -> dict[str, Any]:
        """Create one responsive search ad from plain text. Changes the live account.

        headlines: 3-15, up to 30 characters each. descriptions: 2-4, up to 90 each.
        pins maps a headline or description text to a position, e.g.
        {"Acme Running": "Headline1", "Free returns": "Description1"}. path1/path2
        are the display URL paths (up to 15 characters). Lengths are checked
        before anything is sent; editorial review happens after creation.
        """
        ad = build_rsa(
            headlines=headlines,
            descriptions=descriptions,
            final_urls=final_urls,
            path1=path1,
            path2=path2,
            pins=pins,
            status=status,
        )
        return entity_tools["create"](ad_group_id, [ad], account_id, customer_id, confirm)
