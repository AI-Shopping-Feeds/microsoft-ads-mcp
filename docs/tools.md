# Tools

**70 tools**, all prefixed `microsoft_ads_`, in 14 groups plus 5 server tools that are
always registered. They use the Microsoft Advertising REST API v13.

- **Kind**: *read* changes nothing; *read (starts a job)* requests a report or bulk
  download; *write* creates or changes something; *destructive* deletes; *local* touches
  only this server.
- **Confirm**: the `confirm` word a guarded call needs. `DELETE` for deletes.
  `APPLY` when a write touches more than `MICROSOFT_ADS_BULK_THRESHOLD` items (10), raises
  a bid or budget by more than `MICROSOFT_ADS_MAX_INCREASE_PCT` (20%) or can't read the
  current value, goes over `MICROSOFT_ADS_MAX_DAILY_BUDGET` / `MICROSOFT_ADS_MAX_BID`,
  enables campaigns, applies recommendations, or is a raw write. A refused call returns
  what it would have sent and why. In dry-run nothing is sent and guards don't block.
- Entity objects use Microsoft's own field names (`Id`, `Status`, `DailyBudget`,
  `CpcBid`, `Type`...). IDs are strings. Batch writes can partly succeed: failed items
  come back in `PartialErrors`, summarised in `partial_error_summary`.
- Most tools take `account_id` and `customer_id`. They default to
  `MICROSOFT_ADS_ACCOUNT_ID` and `MICROSOFT_ADS_CUSTOMER_ID`; if no customer is set, the
  account's parent customer is looked up once.
- Limit what is registered with `MICROSOFT_ADS_TOOL_GROUPS` (the group names below) or
  `MICROSOFT_ADS_READ_ONLY=true` (only *read* tools plus the server tools).

## server (always on)

| Tool | Kind | Confirm | What it does |
|---|---|---|---|
| `microsoft_ads_describe_server` | local | | Show which environment, default account and safety settings this server uses. |
| `microsoft_ads_health_check` | read | | Refresh the access token, read the signed-in user and list the accounts they can access. |
| `microsoft_ads_audit_lookup` | local | | Look up an audit log entry by ID: the request, response and before-snapshot of a write. |
| `microsoft_ads_audit_tail` | local | | Show the most recent audit log entries (writes and dry-run rehearsals). |
| `microsoft_ads_set_dry_run` | local | | Turn dry-run on or off for this session. |

## accounts

| Tool | Kind | Confirm | What it does |
|---|---|---|---|
| `microsoft_ads_get_user` | read | | Show the signed-in Microsoft Advertising user and their roles per customer. |
| `microsoft_ads_list_accounts` | read | | List the ad accounts the signed-in user can access, or the accounts of one customer (manager account). |
| `microsoft_ads_get_account` | read | | Get one ad account's settings (billing and tax details are left out). |
| `microsoft_ads_list_customers` | read | | List the customers (manager accounts) the signed-in user can access, optionally filtered by the start of the name. |

## campaigns

| Tool | Kind | Confirm | What it does |
|---|---|---|---|
| `microsoft_ads_list_campaigns` | read | | List campaigns. |
| `microsoft_ads_create_campaigns` | write | `APPLY` if guarded | Create campaigns (up to 100 per call). |
| `microsoft_ads_update_campaigns` | write | `APPLY` if guarded | Update campaigns (up to 100 per call). |
| `microsoft_ads_delete_campaigns` | destructive | `DELETE` | Delete campaigns by ID. |

## ad_groups

| Tool | Kind | Confirm | What it does |
|---|---|---|---|
| `microsoft_ads_list_ad_groups` | read | | List ad groups. |
| `microsoft_ads_create_ad_groups` | write | `APPLY` if guarded | Create ad groups (up to 1000 per call). |
| `microsoft_ads_update_ad_groups` | write | `APPLY` if guarded | Update ad groups (up to 1000 per call). |
| `microsoft_ads_delete_ad_groups` | destructive | `DELETE` | Delete ad groups by ID. |

## ads

| Tool | Kind | Confirm | What it does |
|---|---|---|---|
| `microsoft_ads_list_ads` | read | | List ads. |
| `microsoft_ads_create_ads` | write | `APPLY` if guarded | Create ads (up to 50 per call). |
| `microsoft_ads_update_ads` | write | `APPLY` if guarded | Update ads (up to 50 per call). |
| `microsoft_ads_delete_ads` | destructive | `DELETE` | Delete ads by ID. |
| `microsoft_ads_create_responsive_search_ad` | write | `APPLY` if guarded | Create one responsive search ad from plain text. |

## keywords

| Tool | Kind | Confirm | What it does |
|---|---|---|---|
| `microsoft_ads_list_keywords` | read | | List keywords. |
| `microsoft_ads_create_keywords` | write | `APPLY` if guarded | Create keywords (up to 1000 per call). |
| `microsoft_ads_update_keywords` | write | `APPLY` if guarded | Update keywords (up to 1000 per call). |
| `microsoft_ads_delete_keywords` | destructive | `DELETE` | Delete keywords by ID. |
| `microsoft_ads_list_negative_keywords` | read | | List negative keywords attached directly to campaigns or ad groups. |
| `microsoft_ads_add_negative_keywords` | write | `APPLY` if guarded | Add the same negative keywords to one or more campaigns or ad groups. |
| `microsoft_ads_delete_negative_keywords` | destructive | `DELETE` | Remove negative keywords from one campaign or ad group by negative keyword ID. |

## asset_groups

| Tool | Kind | Confirm | What it does |
|---|---|---|---|
| `microsoft_ads_list_asset_groups` | read | | List Performance Max asset groups. |
| `microsoft_ads_create_asset_groups` | write | `APPLY` if guarded | Create Performance Max asset groups (up to 100 per call). |
| `microsoft_ads_update_asset_groups` | write | `APPLY` if guarded | Update Performance Max asset groups (up to 100 per call). |
| `microsoft_ads_delete_asset_groups` | destructive | `DELETE` | Delete Performance Max asset groups by ID. |

## targeting

| Tool | Kind | Confirm | What it does |
|---|---|---|---|
| `microsoft_ads_list_audiences` | read | | List audiences (remarketing, custom, in-market, product, similar, combined, customer match lists). |
| `microsoft_ads_list_criterions` | read | | List the criterions (targets, exclusions, bid adjustments, audience associations) of one campaign or ad group. |
| `microsoft_ads_add_criterions` | write | `APPLY` if guarded | Add criterions to campaigns or ad groups: targets, exclusions, bid adjustments and audience associations. |
| `microsoft_ads_update_criterions` | write | `APPLY` if guarded | Update criterions (e.g. |
| `microsoft_ads_delete_criterions` | destructive | `DELETE` | Delete criterions from one campaign or ad group (removes targets, exclusions or audience associations). |

## budgets

| Tool | Kind | Confirm | What it does |
|---|---|---|---|
| `microsoft_ads_list_budgets` | read | | List shared budgets. |
| `microsoft_ads_create_budgets` | write | `APPLY` if guarded | Create shared budgets (up to 100 per call). |
| `microsoft_ads_update_budgets` | write | `APPLY` if guarded | Update shared budgets (up to 100 per call). |
| `microsoft_ads_delete_budgets` | destructive | `DELETE` | Delete shared budgets by ID. |
| `microsoft_ads_list_bid_strategies` | read | | List portfolio bid strategies. |
| `microsoft_ads_create_bid_strategies` | write | `APPLY` if guarded | Create portfolio bid strategies (up to 100 per call). |
| `microsoft_ads_update_bid_strategies` | write | `APPLY` if guarded | Update portfolio bid strategies (up to 100 per call). |
| `microsoft_ads_delete_bid_strategies` | destructive | `DELETE` | Delete portfolio bid strategies by ID. |

## labels

| Tool | Kind | Confirm | What it does |
|---|---|---|---|
| `microsoft_ads_list_labels` | read | | List labels. |
| `microsoft_ads_create_labels` | write | `APPLY` if guarded | Create labels (up to 100 per call). |
| `microsoft_ads_update_labels` | write | `APPLY` if guarded | Update labels (up to 100 per call). |
| `microsoft_ads_delete_labels` | destructive | `DELETE` | Delete labels by ID. |
| `microsoft_ads_list_label_associations` | read | | List the labels on campaigns, ad groups, ads or keywords. |
| `microsoft_ads_set_label_associations` | write | `APPLY` if guarded | Attach labels to entities. |
| `microsoft_ads_delete_label_associations` | destructive | `DELETE` | Remove labels from entities. |

## bulk_edits

| Tool | Kind | Confirm | What it does |
|---|---|---|---|
| `microsoft_ads_set_status` | write | `APPLY` if guarded | Pause or enable many campaigns, ad groups, asset groups, ads or keywords at once. |
| `microsoft_ads_adjust_bids` | write | `APPLY` if guarded | Raise or lower ad group default bids or keyword bids by a percentage. |

## reporting

| Tool | Kind | Confirm | What it does |
|---|---|---|---|
| `microsoft_ads_submit_report` | read (starts a job) | | Submit a report request. |
| `microsoft_ads_poll_report` | read | | Check a report's status: Pending, Success or Error. |
| `microsoft_ads_download_report` | read | | Download a finished report and return its rows (up to max_rows). |
| `microsoft_ads_run_report` | read (starts a job) | | Submit a report, wait for it with progress updates, and return its rows. |
| `microsoft_ads_change_history` | read (starts a job) | | Who changed what, and when, in one account: runs the change history report. |

## insights

| Tool | Kind | Confirm | What it does |
|---|---|---|---|
| `microsoft_ads_keyword_ideas` | read | | Get keyword ideas with monthly searches, competition and suggested bids. |
| `microsoft_ads_keyword_traffic_estimates` | read | | Estimate weekly impressions, clicks, cost, CTR and average CPC for keywords at a given max CPC, in the given locations and language. |
| `microsoft_ads_estimated_bids` | read | | Estimate the bid needed to reach a position (MainLine1, MainLine or FirstPage) for keywords, with estimated clicks, impressions and cost. |
| `microsoft_ads_budget_opportunities` | read | | Get Microsoft's budget suggestions for a campaign that is limited by budget, with the estimated extra impressions and clicks. |
| `microsoft_ads_list_recommendations` | read | | List Microsoft's recommendations for the account (or one campaign or ad group), optionally of one recommendation_type. |
| `microsoft_ads_apply_recommendations` | write | `APPLY` always | Apply recommendations from microsoft_ads_list_recommendations. |
| `microsoft_ads_dismiss_recommendations` | write | `APPLY` if guarded | Dismiss recommendations so they stop showing. |

## bulk

| Tool | Kind | Confirm | What it does |
|---|---|---|---|
| `microsoft_ads_bulk_download` | read (starts a job) | | Download one account's entities with the Bulk service and return the rows. |

## request

| Tool | Kind | Confirm | What it does |
|---|---|---|---|
| `microsoft_ads_read_request` | read | | Call any read-only Microsoft Advertising REST operation the other tools don't cover. |
| `microsoft_ads_request` | destructive | `APPLY` always | Call any Microsoft Advertising REST v13 operation the other tools don't cover. |

## Not covered by dedicated tools

Use `microsoft_ads_read_request` / `microsoft_ads_request` with a v13 REST path for
anything else in Campaign Management, Customer Management, Customer Billing, Reporting,
Ad Insight or Bulk: ad extensions and assets, shared negative keyword lists and
placement exclusion lists (`SharedEntities`), conversion goals and UET tags,
experiments, product partitions (`ProductPartitionActions/Apply`), asset group listing
groups, audiences (create/update), auction insights, bid landscapes and so on. Paths
look like `/CampaignManagement/v13/SharedEntities/QueryByAccountId`; find them in
Microsoft's REST API reference. Bulk upload is not offered.
