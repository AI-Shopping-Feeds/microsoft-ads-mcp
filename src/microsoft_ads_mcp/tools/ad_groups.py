"""Ad groups in Search, Shopping and Audience campaigns."""

from __future__ import annotations

from .. import safety
from ..client import MicrosoftAdsClient
from ._common import EntitySpec, register_entity

SPEC = EntitySpec(
    noun="ad_groups",
    label="ad groups",
    resource="AdGroups",
    ids_key="AdGroupIds",
    parent="campaign",
    list_op="QueryByCampaignId",
    max_items=1000,
    money=safety.AD_GROUP_MONEY,
    create_defaults={"Status": "Paused"},
    create_example=(
        'e.g. {"Name": "Trainers", "CpcBid": {"Amount": 0.6}}. New ad groups are created '
        "Paused unless Status is set to Active."
    ),
    update_example='e.g. {"Id": "456", "CpcBid": {"Amount": 0.7}} or {"Id": "456", "Status": "Active"}.',
)


def register(mcp, client: MicrosoftAdsClient) -> None:
    register_entity(mcp, client, SPEC)
