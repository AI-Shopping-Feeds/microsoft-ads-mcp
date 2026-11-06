# Contributing

Thanks for helping improve the Microsoft Ads MCP server.

## Development setup

```bash
git clone https://github.com/AI-Shopping-Feeds/microsoft-ads-mcp.git
cd microsoft-ads-mcp
uv venv && uv pip install -e ".[test,dev]"
```

Without uv: `python -m venv .venv && .venv/bin/pip install -e ".[test,dev]"` (Python 3.11 or
later). To try it against an account, follow [docs/setup-microsoft-ads-api.md](docs/setup-microsoft-ads-api.md);
the sandbox (`MICROSOFT_ADS_ENVIRONMENT=sandbox`) is the safest place to test writes.

## Checks

```bash
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/mypy src/microsoft_ads_mcp
.venv/bin/pytest
```

Tests run offline: HTTP is mocked with `respx`, and no Microsoft credentials are needed.
`pre-commit install` runs the same checks before each commit.

## Pull requests

- Keep secrets, tokens and account data out of commits, tests and issues. Use obviously
  fake values in tests.
- New tools go in the matching module under `src/microsoft_ads_mcp/tools/`, use the
  `microsoft_ads_` prefix, and need an entry in `tool_catalog.py` (title and annotations)
  and a row in `docs/tools.md`. `tests/test_mcp_client.py` fails otherwise.
- Writes go through `MicrosoftAdsClient.request` so they follow dry-run and the audit log,
  and use `safety.assess` / `safety.refusal` for confirm words (`DELETE` for deletes,
  `APPLY` for batches and spend rises).
- Build only on the REST API v13. Don't add SOAP.
- Never paste Microsoft documentation text, WSDL or OpenAPI files, or SDK or sample code
  into the repository. Write your own descriptions and link to Microsoft's docs instead.
- Use "Microsoft Advertising" only to describe what the server works with, and no logos.
- Update the README and CHANGELOG when tools, settings or setup change.
