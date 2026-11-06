# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-11-06

### Added
- First version: 70 tools in 14 groups plus 5 always-on server tools, on the Microsoft
  Advertising REST API v13 (no SOAP, which Microsoft retires on 31 January 2027).
- Sign-in with the Microsoft identity platform: `microsoft-ads-mcp auth` runs the
  authorization code flow with PKCE and a localhost callback, or `--manual` paste mode that
  requires a matching `state`. Work, school and personal Microsoft accounts are supported.
  Access tokens are cached until shortly before expiry; rotated refresh tokens are saved.
- Production and sandbox environments (`MICROSOFT_ADS_ENVIRONMENT`); the sandbox uses
  Microsoft's universal sandbox developer token by default.
- Every request sends the developer token and, where needed, `CustomerId` and
  `CustomerAccountId` from `account_id`/`customer_id` or the defaults; the customer is looked
  up from the account when unset.
- Customer Management (user, accounts, customers); Campaign Management for campaigns, ad
  groups, ads (with a responsive search ad helper), keywords, campaign and ad group
  negative keywords, Performance Max asset groups, audiences and criterions, shared budgets,
  portfolio bid strategies and labels; quick `set_status` and `adjust_bids`.
- Reporting: submit, poll, download (zipped CSV parsed in memory) and `run_report` with
  progress; `change_history`.
- Ad Insight: keyword ideas, traffic estimates, bid estimates, budget opportunities and
  recommendations (list, apply, dismiss). Bulk download of an account's entities.
- Read-only and confirm-gated raw request tools for any other REST v13 operation.
- Safety: dry-run, confirm words (`DELETE`, `APPLY`), spend guards
  (`MICROSOFT_ADS_MAX_INCREASE_PCT` 20%, optional daily budget and bid caps), new campaigns,
  ad groups and asset groups created paused, before-snapshots, read-only mode, tool groups.
- Data handling: per-user `~/.microsoft-ads-mcp/` folder (0700, files 0600), redacted audit
  log of writes pruned after 30 days, `purge`, downloads capped at 200 MB, only Microsoft
  hosts called, HTTP transports refuse non-loopback hosts unless opted in.
