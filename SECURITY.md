# Security

This server can create, change, pause and delete Microsoft Advertising campaigns, ads,
keywords, targeting, budgets and bids, which spends real money, and it can read account
performance data. It acts with the permissions of the Microsoft user who signed in.

## Protect your credentials

- The refresh token lives in `~/.microsoft-ads-mcp/secrets/microsoft-ads-token.json`. The
  folder is created owner-only (0700) and the file 0600. Keep it that way, and never commit
  it or paste it into chat.
- Treat the developer token and any client secret like passwords. Keep them in your MCP
  client's config or `~/.microsoft-ads-mcp/.env`, never in a repository (`.env` and
  `secrets/` are git-ignored here).
- If a machine is lost or a token leaks: remove the app from the Microsoft account's app
  permissions (or change the password) to revoke refresh tokens, regenerate the developer
  token in Microsoft Advertising **Settings > Developer settings**, rotate any client secret
  in the Azure portal, then run `microsoft-ads-mcp purge`.
- Use a dedicated app registration for this server, and a Microsoft Advertising user with
  only the roles it needs. `MICROSOFT_ADS_READ_ONLY=true` removes every write tool.

## Never expose the HTTP transport

The `streamable-http` and `sse` transports have no sign-in: anyone who can reach the port
can use your credentials. The server refuses to bind to anything but `127.0.0.1`,
`localhost` or `::1` unless you set `MICROSOFT_ADS_ALLOW_REMOTE=true` (or `--allow-remote`).
Only do that behind your own authentication. Prefer stdio.

## What the server stores

Only the refresh token and an audit log of writes (redacted, owner-only, pruned after 30
days). Report and bulk data stay in memory. See [docs/terms-and-data.md](docs/terms-and-data.md).

## Reporting vulnerabilities, misuse or data incidents

Report security problems privately through a
[GitHub private security advisory](https://github.com/AI-Shopping-Feeds/microsoft-ads-mcp/security/advisories/new)
on this repository, or contact the maintainers at
[AI Shopping Feeds](https://github.com/AI-Shopping-Feeds). Use the same route to report
suspected misuse of Microsoft Advertising data or credentials through this software. Don't
post working exploits, tokens or account data in a public issue. We aim to reply within
five working days.

Problems with Microsoft's own services or your Microsoft account belong with
[Microsoft Advertising support](https://about.ads.microsoft.com/en/support).
