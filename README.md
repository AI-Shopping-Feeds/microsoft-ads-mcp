<!-- mcp-name: io.github.AI-Shopping-Feeds/microsoft-ads-mcp -->

# Microsoft Ads MCP Server (read + write)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE) [![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/downloads/)

An [MCP](https://modelcontextprotocol.io) server for Microsoft Advertising, using the
[Microsoft Advertising REST API v13](https://learn.microsoft.com/en-us/advertising/guides/?view=bingads-13)
(the API formerly called the Bing Ads API). Use it from Claude, ChatGPT, Cursor, Codex or any
MCP client to report on Search, Shopping and Performance Max campaigns, find keywords, and
change campaigns, ad groups, ads, keywords, targeting, budgets and bids.

Maintained by [AI Shopping Feeds](https://github.com/AI-Shopping-Feeds). It offers:

- **Coverage of the advertiser workflow**: accounts, campaigns, ad groups, ads (with a
  responsive search ad helper), keywords and negatives, Performance Max asset groups,
  targeting and audiences, shared budgets, portfolio bid strategies, labels, reports,
  change history, keyword ideas, estimates, recommendations and bulk download
- **Safety**: dry-run, confirm words for deletes, big batches and spend rises, new
  campaigns created paused, an audit log with before-snapshots, read-only mode and tool groups
- **An escape hatch** for every other REST v13 operation, read-only or confirm-gated

Microsoft also runs a hosted [Microsoft Advertising MCP Server](https://learn.microsoft.com/en-us/advertising/guides/mcp-setup?view=bingads-13)
that you connect with your own Entra app. Its documented scenarios are reporting, analysis,
assets and change history. This one runs on your own machine and adds guarded write tools.
More in [docs/terms-and-data.md](docs/terms-and-data.md#microsofts-own-mcp-server).

Not affiliated with or endorsed by Microsoft.

Part of the AI Shopping Feeds MCP family: [Google Ads](https://github.com/AI-Shopping-Feeds/google-ads-mcp) · [Google Merchant Centre](https://github.com/AI-Shopping-Feeds/google-merchant-centre-mcp) · [Google Analytics](https://github.com/AI-Shopping-Feeds/google-analytics-mcp) · [YouTube Studio](https://github.com/AI-Shopping-Feeds/youtube-studio-mcp) · [Amazon Ads](https://github.com/AI-Shopping-Feeds/amazon-ads-mcp) · [Apple Ads](https://github.com/AI-Shopping-Feeds/apple-ads-mcp) · **Microsoft Ads** · [TikTok Ads](https://github.com/AI-Shopping-Feeds/tiktok-ads-mcp) · [Pinterest Ads](https://github.com/AI-Shopping-Feeds/pinterest-ads-mcp) · [Snapchat Ads](https://github.com/AI-Shopping-Feeds/snapchat-ads-mcp) · [OpenAI Ads](https://github.com/AI-Shopping-Feeds/openai-ads-mcp) · [AppLovin](https://github.com/AI-Shopping-Feeds/applovin-mcp).

## Let your agent set it up

Paste this into Claude Code, Codex, Cursor or any agent that can read web pages and edit files:

```text
Set up the Microsoft Ads MCP server for me by following https://raw.githubusercontent.com/AI-Shopping-Feeds/microsoft-ads-mcp/main/skills/microsoft-ads-mcp/SKILL.md
```

The agent checks whether it's already connected, installs the runner if you agree, walks
you through the developer token, the Entra app registration and sign-in, adds the server
to your client's config without touching your other servers, and checks it works by
calling `microsoft_ads_health_check`.

The same file is an [Agent Skill](https://agentskills.io), so your agent can keep it as a
guide to using the tools well. For Claude Code, copy the folder into your skills:

```bash
git clone --depth 1 https://github.com/AI-Shopping-Feeds/microsoft-ads-mcp.git /tmp/microsoft-ads-mcp
cp -r /tmp/microsoft-ads-mcp/skills/microsoft-ads-mcp ~/.claude/skills/
```

Other agents that support skills load the same `skills/microsoft-ads-mcp` folder from their
own skills directory.

## What it can do

70 tools, all prefixed `microsoft_ads_`. The full list is in [docs/tools.md](docs/tools.md).

### Read

| Area | Tools |
|---|---|
| Accounts | `get_user`, `list_accounts`, `get_account`, `list_customers` |
| Structure | `list_campaigns`, `list_ad_groups`, `list_ads`, `list_keywords`, `list_asset_groups`, `list_negative_keywords` |
| Targeting | `list_audiences`, `list_criterions` (locations, devices, schedules, audiences, product partitions) |
| Budgets and labels | `list_budgets`, `list_bid_strategies`, `list_labels`, `list_label_associations` |
| Reports | `run_report` (submit, wait and return rows), `submit_report`, `poll_report`, `download_report`, `change_history` |
| Insights | `keyword_ideas`, `keyword_traffic_estimates`, `estimated_bids`, `budget_opportunities`, `list_recommendations` |
| Bulk and anything else | `bulk_download`, `read_request` |

### Write

| Area | Tools |
|---|---|
| Campaigns and ad groups | `create_`, `update_`, `delete_campaigns`; `create_`, `update_`, `delete_ad_groups` |
| Ads | `create_ads`, `create_responsive_search_ad`, `update_ads`, `delete_ads` |
| Keywords | `create_`, `update_`, `delete_keywords`, `add_negative_keywords`, `delete_negative_keywords` |
| Performance Max | `create_`, `update_`, `delete_asset_groups` |
| Targeting | `add_criterions`, `update_criterions`, `delete_criterions` |
| Budgets and bidding | `create_`, `update_`, `delete_budgets`; `create_`, `update_`, `delete_bid_strategies` |
| Labels | `create_`, `update_`, `delete_labels`, `set_label_associations`, `delete_label_associations` |
| Quick edits | `set_status` (pause or enable many), `adjust_bids` (by a percentage) |
| Recommendations | `apply_recommendations`, `dismiss_recommendations` |
| Any operation | `request` |

### Safety

- **Dry-run** (`MICROSOFT_ADS_DRY_RUN=true` or `microsoft_ads_set_dry_run`) records writes and returns a preview without sending them.
- **Confirm words**: deletes need `confirm="DELETE"`. Batches over 10 items, bid or budget rises over 20% (or where the current value can't be read), values over your caps, enabling campaigns, applying recommendations and raw writes need `confirm="APPLY"`. A refused call shows what it would send.
- **New campaigns, ad groups and asset groups are created paused** unless you set `Status`.
- **Audit log** of every write and rehearsal, with a before-snapshot, in `~/.microsoft-ads-mcp/logs/audit.jsonl` (owner-only). Entries older than 30 days are pruned; `microsoft-ads-mcp purge` deletes the log and the stored token. Report rows stay in memory and downloads are capped at 200 MB.
- **Read-only mode** (`MICROSOFT_ADS_READ_ONLY=true`) and **tool groups** (`MICROSOFT_ADS_TOOL_GROUPS`) limit what the agent can see.
- **Spend guards**: `MICROSOFT_ADS_MAX_INCREASE_PCT`, `MICROSOFT_ADS_MAX_DAILY_BUDGET` and `MICROSOFT_ADS_MAX_BID`.
- The HTTP transports **refuse to bind to a non-loopback address** unless you set `MICROSOFT_ADS_ALLOW_REMOTE=true`.
- Only Microsoft Advertising and Microsoft sign-in hosts are called. Terms, data handling and limits: [docs/terms-and-data.md](docs/terms-and-data.md).

## Supported clients

| Client | Works? | How |
|---|---|---|
| Claude Code | ✅ | Local server, `claude mcp add` (below) |
| Claude Desktop | ✅ | Local server, `claude_desktop_config.json` |
| Cursor | ✅ | Local server, `~/.cursor/mcp.json` |
| VS Code (Copilot) | ✅ | Local server, `.vscode/mcp.json` (uses `servers` instead of `mcpServers`) |
| Codex | ✅ | Local server, `~/.codex/config.toml` |
| Gemini CLI | ✅ | Local server, `~/.gemini/settings.json` |
| Windsurf and other local clients | ✅ | Local server, same JSON entry |
| Claude.ai and ChatGPT | ❌ not yet | These need a remote server with sign-in. This server's HTTP transports have no sign-in, so don't expose them publicly. Use a local client. |

## Setup

### 1. Install uv

The server runs with `uvx` from [uv](https://docs.astral.sh/uv/getting-started/installation/)
(`brew install uv` on macOS) and needs Python 3.11 or later. It installs straight from this
repository:

```shell
uvx --from git+https://github.com/AI-Shopping-Feeds/microsoft-ads-mcp.git microsoft-ads-mcp
```

Pin a release by adding `@vX.Y.Z` to the URL.

### 2. Get credentials

1. **Developer token**: a Super Admin of your Microsoft Advertising account requests one in
   Microsoft Advertising under **Settings > Developer settings**. Microsoft says it is issued
   straight away for your own accounts and can take up to five business days if you manage
   other people's accounts. Not needed for the sandbox.
2. **App registration**: in the Azure portal (**Microsoft Entra ID > App registrations**),
   register an app for **any organisational directory and personal Microsoft accounts**,
   and add the redirect URI `http://localhost:8765/callback` under **Mobile and desktop
   applications**. Copy the **Application (client) ID**.
3. **Sign in** once with the Microsoft account that manages the ads:

   ```shell
   MICROSOFT_ADS_CLIENT_ID=your-client-id MICROSOFT_ADS_DEVELOPER_TOKEN=your-developer-token \
     uvx --from git+https://github.com/AI-Shopping-Feeds/microsoft-ads-mcp.git microsoft-ads-mcp auth
   ```

   It saves a refresh token to `~/.microsoft-ads-mcp/secrets/microsoft-ads-token.json`
   (owner-only). Add `--manual` if the browser can't reach localhost.

Step by step, with the sandbox, agencies and troubleshooting: [docs/setup-microsoft-ads-api.md](docs/setup-microsoft-ads-api.md).

### 3. Add it to your client

Replace the placeholders. Keep your other servers in each file. The token file from step 2
is found automatically.

**Claude Code**

```bash
claude mcp add --scope user microsoft-ads \
  --env MICROSOFT_ADS_CLIENT_ID=your-client-id \
  --env MICROSOFT_ADS_DEVELOPER_TOKEN=your-developer-token \
  --env MICROSOFT_ADS_ACCOUNT_ID=123456789 \
  -- uvx --from git+https://github.com/AI-Shopping-Feeds/microsoft-ads-mcp.git microsoft-ads-mcp
```

**Claude Desktop, Cursor, Gemini CLI, Windsurf** (and VS Code under `servers`)

```json
{
  "mcpServers": {
    "microsoft-ads": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/AI-Shopping-Feeds/microsoft-ads-mcp.git", "microsoft-ads-mcp"],
      "env": {
        "MICROSOFT_ADS_CLIENT_ID": "your-client-id",
        "MICROSOFT_ADS_DEVELOPER_TOKEN": "your-developer-token",
        "MICROSOFT_ADS_ACCOUNT_ID": "123456789"
      }
    }
  }
}
```

Desktop apps often can't find `uvx` on the PATH; if the server doesn't start, use the full
path from `which uvx` as the `command`. If you keep the token somewhere else, add
`"MICROSOFT_ADS_TOKEN_FILE": "/abs/path/microsoft-ads-token.json"`.

**Codex** (`~/.codex/config.toml`)

```toml
[mcp_servers.microsoft-ads]
command = "uvx"
args = ["--from", "git+https://github.com/AI-Shopping-Feeds/microsoft-ads-mcp.git", "microsoft-ads-mcp"]
env = { MICROSOFT_ADS_CLIENT_ID = "your-client-id", MICROSOFT_ADS_DEVELOPER_TOKEN = "your-developer-token", MICROSOFT_ADS_ACCOUNT_ID = "123456789" }
```

You can also put these settings in `~/.microsoft-ads-mcp/.env` instead of the client config.

### 4. Check it works

Restart or reload the client, then ask it "which Microsoft Advertising accounts can you
see?". It should call `microsoft_ads_health_check` and list your accounts. Set
`MICROSOFT_ADS_ACCOUNT_ID` to the one you use most; tools also take an `account_id`.

## Configuration

| Variable | Required | What it does |
|---|---|---|
| `MICROSOFT_ADS_CLIENT_ID` | yes | Application (client) ID of your Entra app registration |
| `MICROSOFT_ADS_DEVELOPER_TOKEN` | production | Developer token (the sandbox uses Microsoft's universal sandbox token) |
| `MICROSOFT_ADS_ENVIRONMENT` | no | `production` (default) or `sandbox`; they use separate credentials |
| `MICROSOFT_ADS_CLIENT_SECRET` | no | Only for apps registered as Web apps with a secret |
| `MICROSOFT_ADS_TENANT` | no | Sign-in tenant (default `common`: work, school and personal accounts) |
| `MICROSOFT_ADS_TOKEN_FILE` | no | Refresh-token file written by `auth` (default `~/.microsoft-ads-mcp/secrets/microsoft-ads-token.json`) |
| `MICROSOFT_ADS_REFRESH_TOKEN` | no | The refresh token itself, instead of the file |
| `MICROSOFT_ADS_ACCOUNT_ID`, `MICROSOFT_ADS_CUSTOMER_ID` | no | Default account, and its customer (looked up from the account if unset) |
| `MICROSOFT_ADS_DRY_RUN` | no | `true` previews writes without sending them |
| `MICROSOFT_ADS_READ_ONLY` | no | `true` registers only read-only tools |
| `MICROSOFT_ADS_TOOL_GROUPS` | no | Comma-separated groups: `accounts`, `campaigns`, `ad_groups`, `ads`, `keywords`, `asset_groups`, `targeting`, `budgets`, `labels`, `bulk_edits`, `reporting`, `insights`, `bulk`, `request`. Unknown names stop the server at startup |
| `MICROSOFT_ADS_BULK_THRESHOLD` | no | Items per write before `confirm="APPLY"` is needed (default 10) |
| `MICROSOFT_ADS_MAX_INCREASE_PCT` | no | Bid/budget rise that needs `confirm="APPLY"` (default 20) |
| `MICROSOFT_ADS_MAX_DAILY_BUDGET`, `MICROSOFT_ADS_MAX_BID` | no | Optional absolute caps |
| `MICROSOFT_ADS_AUDIT_LOG` | no | Audit log path (default `~/.microsoft-ads-mcp/logs/audit.jsonl`) |
| `MICROSOFT_ADS_AUDIT_RETENTION_DAYS` | no | Days to keep audit entries, pruned at startup (default 30; 0 keeps them) |
| `MICROSOFT_ADS_MAX_DOWNLOAD_MB` | no | Largest report or bulk file to download (default 200) |
| `MICROSOFT_ADS_HOME` | no | Per-user folder for secrets, logs and `.env` (default `~/.microsoft-ads-mcp`) |
| `MICROSOFT_ADS_TIMEOUT`, `MICROSOFT_ADS_LOG_LEVEL` | no | Request timeout in seconds (60) and log level (logs go to stderr) |
| `MICROSOFT_ADS_TRANSPORT`, `MICROSOFT_ADS_HOST`, `MICROSOFT_ADS_PORT` | no | `stdio` (default) or `streamable-http` at `http://HOST:PORT/mcp` (`sse` is deprecated). Default bind `127.0.0.1:8000` |
| `MICROSOFT_ADS_ALLOW_REMOTE` | no | `true` (or `--allow-remote`) allows binding HTTP to a non-loopback host. The server has no sign-in, so only do this behind your own authentication |

Settings are read from the environment, `--env FILE`, `./.env` and then
`~/.microsoft-ads-mcp/.env`. CLI: `microsoft-ads-mcp run` (default), `auth`, `purge`,
`describe`, `version`.

## Example prompts

```text
Which campaigns spent the most last week, and what was their cost per conversion?
```

```text
Lower keyword bids by 10% in the "Running shoes" ad group for keywords with no conversions in 30 days. Dry-run first and show me the table.
```

```text
Add "free" and "cheap" as phrase negatives to all my Search campaigns.
```

```text
What changed in the account in the last seven days, and who changed it?
```

## More docs

- [All tools and confirm words](docs/tools.md)
- [Getting Microsoft Advertising API access, step by step](docs/setup-microsoft-ads-api.md)
- [Terms, data handling and Microsoft's own MCP server](docs/terms-and-data.md)
- [Agent skill](skills/microsoft-ads-mcp/SKILL.md): setup and usage guide for agents
- [Changelog](CHANGELOG.md) and [security policy](SECURITY.md)

## Contributing and licence

Issues and pull requests are welcome on [this repository](https://github.com/AI-Shopping-Feeds/microsoft-ads-mcp). See
[CONTRIBUTING.md](CONTRIBUTING.md).

Licensed under the [MIT License](LICENSE).

---

Try out [AI Shopping Feeds](https://aishoppingfeeds.com/), our shopping feed management tool (including Google Shopping feeds).
