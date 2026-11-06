# Terms, data handling and Microsoft's own MCP server

Using the Microsoft Advertising API means accepting Microsoft's terms. This server is built
to fit them, but you are responsible for how you use it. This page is a summary, not legal
advice; read the documents themselves. Reviewed 6 November 2026.

## Which terms apply

| Document | When you accept it | What matters here |
|---|---|---|
| [Microsoft Advertising Agreement](https://help.ads.microsoft.com/apex/index/3/en/52034) (current online terms dated August 2025) | By signing up for or using Microsoft Advertising | Prohibitions (Section 3), agency authorisation (preamble), data and privacy (Sections 8 and 9) |
| Developer terms shown when a Super Admin requests a developer token in **Settings > Developer settings** | When requesting the token | We could not view this page without signing in. Third-party guides name it the Microsoft Developer Services Agreement; Microsoft's public [Microsoft Developer Agreement](https://learn.microsoft.com/en-us/legal/mdsa) (last updated June 2018) is summarised below. Check what your token page shows. |
| [Microsoft Advertising Policies](https://go.microsoft.com/fwlink?LinkId=398341) | Part of the Agreement | Ad content and editorial rules apply to ads made through the API too |
| [Microsoft Trademark and Brand Guidelines](https://www.microsoft.com/en-us/legal/intellectualproperty/trademarks) | When using Microsoft names | How the name "Microsoft" may appear (see flag (b)) |
| [Microsoft identity platform](https://learn.microsoft.com/en-us/advertising/guides/authentication-oauth?view=bingads-13) app registration | When registering the Entra app | Your app's credentials are yours to protect |

## What the terms require, and how the server handles it

| Requirement | Source (short quote) | In this server |
|---|---|---|
| Use the API, not scraping | Agreement §3(c) bars "automated means or form of scraping or data extraction" | Only the official REST API is called. No web pages are fetched. |
| Don't build copies of the data | Developer Agreement 1.2(b)(xi): no "build databases or otherwise create copies of any data" | Reads and report rows are returned to the client and kept in memory only. No local database or cache. |
| Delete data you no longer need | Developer Agreement 3.2(e): "promptly delete all data and Content collected or processed" | `microsoft-ads-mcp purge` deletes the audit log and the stored refresh token. |
| Delete personal data within 30 days | Developer Agreement 3.2(f): "within 30 days of receiving the data" | The audit log holds writes only and is pruned after `MICROSOFT_ADS_AUDIT_RETENTION_DAYS` (default 30). `microsoft_ads_get_user` returns no contact details; billing and tax details are dropped from account results. |
| Protect credentials | Developer Agreement 1.1(b)(i): "Keep them secret. Do not try to circumvent them." | Token file and folders are owner-only (0600/0700); tokens, secrets and the developer token are redacted from logs, errors and the audit log; `describe` never prints them. |
| Don't get around limits | Developer Agreement 1.2(b)(ii): no circumventing "any mechanism that limits your use" | HTTP 429 and 5xx back off (honouring `Retry-After`); `CallRateExceeded` (code 117) waits the 60 seconds Microsoft asks for. Reports and bulk downloads poll gently. |
| Only act for authorised advertisers | Agreement preamble: "authorized to act on behalf of the Advertiser" | The server only sees what the signed-in user can see. The agent instructions say to manage only accounts the user is authorised to manage. |
| No extra permissions | Get started guide: a developer token "does not grant additional permissions" | Nothing in the server widens access. |
| Don't resell the service | Developer Agreement 1.2(b)(iii): no "resell, transfer, or sublicense any Services" | It is a self-hosted tool. HTTP transports refuse non-loopback hosts unless you opt in. |
| No Microsoft materials | Microsoft documentation and SDKs are Microsoft's | This repository contains its own code and tool descriptions. No Microsoft SDK, sample code, WSDL/OpenAPI files or documentation text are included; field names are used only to call the API. |
| Only Microsoft hosts | — | Calls go to the six `*.api.bingads.microsoft.com` service hosts for your environment and `login.microsoftonline.com`. Report and bulk files come from the signed link Microsoft returns, accepted only over HTTPS from Microsoft or Azure Blob Storage hosts, capped at `MICROSOFT_ADS_MAX_DOWNLOAD_MB`. No telemetry. The raw request tools take a path, not a URL. |
| Descriptive brand use only | Brand guidelines: "Don't imply an affiliation, endorsement, sponsorship, or approval" | "Microsoft Advertising" is used only to say what the server works with. No logos. The README says it is not affiliated with or endorsed by Microsoft. |

The Agreement has no clause, that we found, forbidding combining Microsoft Advertising data
with other platforms' data (unlike some other ad platforms), so the agent isn't told to keep
data apart. It is told to use account data only for the user's task.

## Flags for the maintainer

**(a) Using it with AI clients such as Claude.** Not blocked. Nothing we read forbids
sending your own Microsoft Advertising data to an AI model you choose, and Microsoft itself
documents connecting its hosted MCP server to Claude and ChatGPT. Two cautions: data
returned by tools goes to the AI provider your client uses, so use business or API terms
under which the provider doesn't train on your inputs; and the Developer Agreement's privacy
duties (3.2) cover personal data such as the user names in the change history report.

**(b) A public repo with "Microsoft" in its name.** This needs a decision. Microsoft's brand
guidelines say "Don't use Microsoft's Brand Assets in the name of your business, product"
(or service, app or domain). The names `microsoft-ads-mcp` / `microsoft_ads_mcp` put the
brand in the product name. Microsoft's own MCP setup guide also uses the label
`microsoft-ads-mcp` for its hosted server, so the name could be mistaken for Microsoft's.
Options: rename before making the repo public (for example a name that doesn't start with
the brand, with "for Microsoft Advertising" in the description), or ask Microsoft. The
"Not affiliated" line and descriptive use reduce, but don't remove, the risk.

**(c) Agencies using it for clients.** Allowed. The agency must be authorised by each
advertiser (Agreement preamble), and the agency is responsible for the advertiser's
obligations if it hasn't bound them to the Agreement. Developer tokens for managing other
people's accounts can take up to five business days. Each person should sign in with their
own Microsoft user; don't run one shared HTTP server for several people or clients.

## Data handling in detail

- **Audit log** (`~/.microsoft-ads-mcp/logs/audit.jsonl`): for each write or dry-run
  rehearsal, the request, a before-snapshot of the entities changed (where the server could
  read them), the response and the account. Never read results or report rows. Redacted,
  owner-only, pruned at startup after 30 days.
- **Refresh token** (`~/.microsoft-ads-mcp/secrets/microsoft-ads-token.json`): written
  owner-only by `microsoft-ads-mcp auth`; replaced when Microsoft rotates it. Revoke it by
  removing the app from your Microsoft account's app permissions, then run `purge`.
- **Reports and bulk files**: downloaded into memory, unzipped (with a size check against
  zip bombs), parsed and returned. Nothing is written to disk.
- **Logs** go to stderr only, at INFO by default, and are redacted.

## API version and deprecations designed around

- Built only on the **REST API v13** (JSON over HTTPS). Microsoft
  [announced](https://about.ads.microsoft.com/en/blog/post/april-2026/evolving-the-microsoft-advertising-api-platform)
  on 1 April 2026 that the **SOAP API is retired on 31 January 2027**; its
  [migration guide](https://learn.microsoft.com/en-us/advertising/guides/migrate-to-rest?view=bingads-13)
  (updated September 2026) says SOAP keeps getting features until then, and that REST is
  the foundation for all future development. No SOAP is used.
- Microsoft's Python SDK moved from `bingads` (SOAP) to `msads` (REST, MIT licence,
  classifiers up to Python 3.12). This server doesn't use either: one small httpx client
  keeps dry-run, audit, confirm and redaction in one place.
- The Developer Portal was replaced by **Settings > Developer settings** in 2025.
- Dynamic Search Ads campaigns were retired (now Search campaigns with dynamic ad groups),
  so `DynamicSearchAds` is left out of the default campaign types.
- Adding a Max CPC to non-portfolio automated bidding schemes now fails (error 611274);
  existing values can still be edited or removed.
- Image ad extensions moved to the V2 `Images` model; `UseOptimizedTargeting` is deprecated
  in favour of `UsePredictiveTargeting`.
- Bulk downloads with a last sync time look back at most 30 days.
- Multi-factor authentication is required for API sign-in, which the
  `msads.manage` scope used here satisfies.

## Rate limits

Microsoft throttles Campaign Management and Ad Insight per user and customer over a
60-second sliding window (error 117, `CallRateExceeded`), limits concurrent report requests
(error 207) and bulk upload/download calls per period (error 4204; wait up to 15 minutes).
The server waits and retries on 117, 429 and 5xx, and reports 207 and 4204 to the agent.

## Microsoft's own MCP server

Microsoft runs a hosted Microsoft Advertising MCP Server at
`https://partner.api.bingads.microsoft.com/ext/mcp/vnext`
([setup](https://learn.microsoft.com/en-us/advertising/guides/mcp-setup?view=bingads-13),
[use cases](https://learn.microsoft.com/en-us/advertising/guides/mcp-use-cases?view=bingads-13)).

| | Microsoft's hosted server | This server |
|---|---|---|
| Where it runs | Microsoft's cloud, as a remote MCP server | Your machine (stdio, or HTTP on localhost) |
| Clients | Copilot Studio, GitHub Copilot in VS Code, ChatGPT and Claude custom connectors | Local MCP clients: Claude Code and Desktop, Cursor, Codex, VS Code, Gemini CLI and others |
| Sign-in | Your own Entra app registration (VS Code can sign in without one); work, school or personal accounts | Your own Entra app plus your developer token |
| Documented scenarios | Reporting and insights, entity lookup, assets, exportable outputs, anomaly detection, 180 days of change history, comparison with Google Ads | The same reads (reports, change history, entities, insights) plus writes |
| Writes | Microsoft's documentation describes analysis only; we could not confirm whether it exposes write tools without connecting a live account | Create, update and delete across campaigns, ad groups, ads, keywords, asset groups, targeting, budgets, bid strategies and labels |
| Safety layer | Not documented | Dry-run, confirm words, spend guards, paused-by-default creates, audit log with before-snapshots, read-only mode, tool groups |
| Cost | No charge stated | Free and open source (MIT) |

Use Microsoft's server if you want a hosted, analysis-only connector in a web client. Use
this one if you want to make changes with guard rails, or keep the connection on your own
machine.
