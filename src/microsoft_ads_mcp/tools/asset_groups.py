"""Performance Max asset groups."""

from __future__ import annotations

from ..client import MicrosoftAdsClient
from ._common import EntitySpec, register_entity

SPEC = EntitySpec(
    noun="asset_groups",
    label="Performance Max asset groups",
    resource="AssetGroups",
    ids_key="AssetGroupIds",
    parent="campaign",
    list_op="QueryByCampaignId",
    max_items=100,
    create_defaults={"Status": "Paused"},
    create_example=(
        "An asset group needs Name, FinalUrls, BusinessName and asset links: Headlines, "
        "LongHeadlines, Descriptions and Images, each a list of AssetLink objects such as "
        '{"Asset": {"Type": "TextAsset", "Text": "Free UK delivery"}}. Images reference '
        "existing image asset IDs. New asset groups are created Paused unless Status is set."
    ),
    update_example='e.g. {"Id": "789", "Status": "Active"} or new Headlines.',
)


def register(mcp, client: MicrosoftAdsClient) -> None:
    register_entity(mcp, client, SPEC)
