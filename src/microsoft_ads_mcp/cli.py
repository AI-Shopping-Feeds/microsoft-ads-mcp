"""CLI entrypoint exposed as the `microsoft-ads-mcp` console script.

Subcommands:

* `microsoft-ads-mcp run`       (default) start the MCP server.
* `microsoft-ads-mcp auth`      one-time Microsoft sign-in; saves the refresh token.
* `microsoft-ads-mcp purge`     delete the audit log and the stored refresh token.
* `microsoft-ads-mcp describe`  print the effective configuration (no secrets).
* `microsoft-ads-mcp version`   print the package version.
"""

from __future__ import annotations

import json
import secrets
import sys
import threading
import time
import webbrowser
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import click

from . import __version__
from ._logging import configure_default, get_logger
from .auth import exchange_code, pkce_pair, redact, register_secret, save_token_file
from .config import (
    LOOPBACK_HOSTS,
    NATIVE_REDIRECT_URI,
    SANDBOX_DEVELOPER_TOKEN,
    SCOPE,
    TRANSPORTS,
    api_hosts,
    app_home,
    audit_log_path,
    load_config,
    load_env,
    token_file_path,
)
from .server import build_server

logger = get_logger("cli")


@click.group(invoke_without_command=True)
@click.option(
    "--env",
    "env_file",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Path to a .env file. Defaults to ./.env, then ~/.microsoft-ads-mcp/.env.",
)
@click.option(
    "--transport",
    type=click.Choice(TRANSPORTS),
    default=None,
    help="Override MICROSOFT_ADS_TRANSPORT. 'sse' is deprecated; use 'streamable-http'.",
)
@click.option(
    "--host", default=None, help="Bind host for streamable-http / sse (default 127.0.0.1)."
)
@click.option(
    "--port", type=int, default=None, help="Bind port for streamable-http / sse (default 8000)."
)
@click.option(
    "--allow-remote",
    is_flag=True,
    default=False,
    help="Allow binding HTTP transports to a non-loopback host (also MICROSOFT_ADS_ALLOW_REMOTE).",
)
@click.pass_context
def cli(
    ctx: click.Context,
    env_file: Path | None,
    transport: str | None,
    host: str | None,
    port: int | None,
    allow_remote: bool,
) -> None:
    """Microsoft Advertising MCP server."""
    ctx.ensure_object(dict)
    ctx.obj["env_file"] = env_file
    ctx.obj["transport"] = transport
    ctx.obj["host"] = host
    ctx.obj["port"] = port
    ctx.obj["allow_remote"] = allow_remote
    if ctx.invoked_subcommand is None:
        ctx.invoke(run)


@cli.command()
@click.pass_context
def run(ctx: click.Context) -> None:
    """Start the MCP server (default subcommand)."""
    configure_default()
    config = load_config(env_file=ctx.obj.get("env_file"))
    if ctx.obj.get("transport"):
        config.transport = ctx.obj["transport"]
    if ctx.obj.get("host"):
        config.host = ctx.obj["host"]
    if ctx.obj.get("port"):
        config.port = ctx.obj["port"]
    if ctx.obj.get("allow_remote"):
        config.allow_remote = True

    if config.transport != "stdio" and config.host not in LOOPBACK_HOSTS:
        if not config.allow_remote:
            raise click.ClickException(
                f"Refusing to bind to {config.host}: the HTTP transports have no sign-in, so "
                "anyone who can reach this address could use your Microsoft Advertising "
                "credentials. Use 127.0.0.1, or set MICROSOFT_ADS_ALLOW_REMOTE=true (or "
                "--allow-remote) if you have put your own authentication in front of it."
            )
        logger.warning(
            "binding to %s: the server has no authentication, so anyone who can reach "
            "this address can use your Microsoft Advertising credentials",
            config.host,
        )

    mcp = build_server(config=config)

    if config.transport == "stdio":
        mcp.run("stdio")
    elif config.transport == "streamable-http":
        logger.info("serving streamable HTTP on http://%s:%d/mcp", config.host, config.port)
        mcp.run("streamable-http", host=config.host, port=config.port)
    elif config.transport == "sse":
        logger.warning(
            "the sse transport (HTTP+SSE) is deprecated by the MCP spec; "
            "use --transport streamable-http instead"
        )
        mcp.run("sse", host=config.host, port=config.port)
    else:
        raise click.ClickException(f"Unknown transport: {config.transport}")


def authorization_url(
    *, authorize_url: str, client_id: str, redirect_uri: str, state: str, code_challenge: str
) -> str:
    query = urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "response_mode": "query",
            "scope": SCOPE,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
    )
    return f"{authorize_url}?{query}"


def parse_redirect(value: str, expected_state: str) -> str:
    """Pull the authorization code out of a pasted redirect URL (or a bare code).

    A pasted URL must carry a `state` that matches the one this run sent.
    """
    value = value.strip()
    if "code=" not in value and "error=" not in value:
        if not value:
            raise click.ClickException("No code given.")
        return value
    query = parse_qs(urlparse(value).query or value.split("?", 1)[-1])
    if "error" in query:
        desc = query.get("error_description", [""])[0].split("\r\n")[0]
        raise click.ClickException(
            f"Microsoft returned an error: {query['error'][0]} {desc}".strip()
        )
    state = query.get("state", [None])[0]
    if state is None:
        raise click.ClickException("The pasted address has no state parameter; start again.")
    if not secrets.compare_digest(state, expected_state):
        raise click.ClickException("The state in the redirect doesn't match; start again.")
    code = query.get("code", [""])[0]
    if not code:
        raise click.ClickException("No code in the redirect URL.")
    return code


def _wait_for_code(port: int, expected_state: str, timeout: float) -> str:
    result: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            if parsed.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            if not secrets.compare_digest(query.get("state", [""])[0], expected_state):
                result["error"] = "state mismatch"
            elif "error" in query:
                result["error"] = query["error"][0]
            elif query.get("code"):
                result["code"] = query["code"][0]
            else:
                result["error"] = "no code in the redirect"
            ok = "code" in result
            self.send_response(200 if ok else 400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            message = (
                "Signed in. You can close this window and return to the terminal."
                if ok
                else "Sign-in failed. Return to the terminal for details."
            )
            self.wfile.write(f"<html><body><p>{message}</p></body></html>".encode())

        def log_message(self, *args: Any, **kwargs: Any) -> None:  # never log the code
            pass

    server = HTTPServer(("127.0.0.1", port), Handler)
    server.timeout = 1
    deadline = time.monotonic() + timeout
    try:
        while not result and time.monotonic() < deadline:
            server.handle_request()
    finally:
        server.server_close()
    if "code" in result:
        return result["code"]
    if "error" in result:
        raise click.ClickException(f"Sign-in failed: {result['error']}")
    raise click.ClickException("Timed out waiting for the browser redirect.")


@cli.command()
@click.option("--port", type=int, default=8765, help="Local callback port (default 8765).")
@click.option(
    "--manual",
    is_flag=True,
    help="Don't start a local server: paste the address you are redirected to instead.",
)
@click.option(
    "--redirect-uri",
    default=None,
    help="Redirect URI registered on the app. Default http://localhost:PORT/callback, "
    f"or {NATIVE_REDIRECT_URI} with --manual.",
)
@click.option(
    "--output",
    "output_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Where to save the refresh token (default MICROSOFT_ADS_TOKEN_FILE or "
    "~/.microsoft-ads-mcp/secrets/microsoft-ads-token.json).",
)
@click.option("--no-browser", is_flag=True, help="Print the sign-in link instead of opening it.")
@click.option(
    "--show-token",
    is_flag=True,
    help="Also print the refresh token once (e.g. to paste into a client config).",
)
@click.option("--timeout", type=float, default=300, help="Seconds to wait for the redirect.")
@click.pass_context
def auth(
    ctx: click.Context,
    port: int,
    manual: bool,
    redirect_uri: str | None,
    output_path: Path | None,
    no_browser: bool,
    show_token: bool,
    timeout: float,
) -> None:
    """One-time Microsoft sign-in: get a refresh token for this server.

    Sign in with the Microsoft account (work, school or personal) that has access
    to the Microsoft Advertising accounts. The redirect URI must be registered on
    your app registration (Azure portal -> App registrations -> Authentication).
    """
    configure_default()
    config = load_config(env_file=ctx.obj.get("env_file"), require_refresh_token=False)
    register_secret(config.client_secret)
    redirect = redirect_uri or (
        NATIVE_REDIRECT_URI if manual else f"http://localhost:{port}/callback"
    )
    state = secrets.token_urlsafe(24)
    verifier, challenge = pkce_pair()
    url = authorization_url(
        authorize_url=config.authorize_url,
        client_id=config.client_id,
        redirect_uri=redirect,
        state=state,
        code_challenge=challenge,
    )
    click.echo(f"Environment: {config.environment}. Redirect URI (must be registered): {redirect}")
    click.echo("Open this link, sign in with the account that manages the ads, and accept:")
    click.echo(url)

    if manual:
        if not no_browser:
            webbrowser.open(url)
        pasted = click.prompt("Paste the full address you were redirected to", hide_input=True)
        code = parse_redirect(pasted, state)
    else:
        if not no_browser:
            threading.Timer(0.5, webbrowser.open, args=(url,)).start()
        click.echo(f"Waiting for the redirect on {redirect} ...")
        code = _wait_for_code(port, state, timeout)

    tokens = exchange_code(
        code=code,
        redirect_uri=redirect,
        client_id=config.client_id,
        client_secret=config.client_secret,
        token_url=config.token_url,
        code_verifier=verifier,
    )
    refresh = tokens["refresh_token"]
    register_secret(refresh)
    target = output_path or config.token_file or token_file_path()
    save_token_file(
        target,
        {
            "refresh_token": refresh,
            "environment": config.environment,
            "tenant": config.tenant,
            "client_id_suffix": config.client_id[-6:],
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        },
    )
    click.echo(f"Saved the refresh token to {target} (owner-only permissions).")
    if target.resolve() != token_file_path().resolve():
        click.echo(f"Set MICROSOFT_ADS_TOKEN_FILE={target.resolve()} so the server finds it.")
    click.echo(
        "Next: run `microsoft-ads-mcp describe`, then add the server to your MCP client. "
        "Never paste the token file into chat or commit it."
    )
    if show_token:
        click.echo(f"Refresh token: {refresh}")


@cli.command()
@click.option("--yes", is_flag=True, help="Don't ask for confirmation.")
@click.option("--keep-token", is_flag=True, help="Delete only the audit log.")
@click.pass_context
def purge(ctx: click.Context, yes: bool, keep_token: bool) -> None:
    """Delete locally stored Microsoft Advertising data: the audit log and the token file."""
    load_env(ctx.obj.get("env_file"))
    audit = audit_log_path()
    targets = [audit, audit.with_suffix(audit.suffix + ".tmp")]
    if not keep_token:
        token = token_file_path()
        targets += [token, token.with_name(token.name + ".tmp")]
    existing = [p for p in targets if p.exists()]
    if not existing:
        click.echo("Nothing to delete.")
        return
    click.echo("Will delete:\n" + "\n".join(f"  {p}" for p in existing))
    if not yes and not click.confirm("Delete these files?", default=False):
        click.echo("Cancelled.")
        return
    for p in existing:
        p.unlink()
    click.echo(f"Deleted {len(existing)} file(s).")
    if not keep_token:
        click.echo(
            "If you also set MICROSOFT_ADS_REFRESH_TOKEN in a client config, remove it there. "
            "To revoke the app's access, remove it from your Microsoft account's app permissions."
        )


@cli.command()
def version() -> None:
    """Print the microsoft-ads-mcp version."""
    click.echo(__version__)


@cli.command("describe")
@click.pass_context
def describe(ctx: click.Context) -> None:
    """Print effective config (environment, account, paths, limits) and exit. No secrets."""
    configure_default()
    config = load_config(env_file=ctx.obj.get("env_file"), require_refresh_token=False)
    info = {
        "version": __version__,
        "environment": config.environment,
        "api_hosts": api_hosts(config.environment),
        "client_id": f"...{config.client_id[-6:]}",
        "client_secret": "set" if config.client_secret else "not set (public client)",
        "developer_token": (
            "sandbox universal token"
            if config.developer_token == SANDBOX_DEVELOPER_TOKEN
            else "set"
        ),
        "tenant": config.tenant,
        "refresh_token": (
            ("set (from MICROSOFT_ADS_REFRESH_TOKEN)" if config.refresh_token_from_env else "set")
            if config.refresh_token
            else "missing (run `microsoft-ads-mcp auth`)"
        ),
        "home": str(app_home()),
        "token_file": str(config.token_file) if config.token_file else None,
        "default_customer_id": config.customer_id,
        "default_account_id": config.account_id,
        "audit_log": str(config.audit_log),
        "audit_retention_days": config.audit_retention_days,
        "dry_run": config.dry_run,
        "read_only": config.read_only,
        "tool_groups": config.tool_groups or "all",
        "bulk_threshold": config.bulk_threshold,
        "max_increase_pct": config.max_increase_pct,
        "max_daily_budget": config.max_daily_budget,
        "max_bid": config.max_bid,
        "max_download_mb": config.max_download_mb,
        "transport": config.transport,
        "host": config.host,
        "port": config.port,
        "allow_remote": config.allow_remote,
    }
    click.echo(json.dumps(info, indent=2, ensure_ascii=False))


def main() -> None:
    try:
        cli(obj={})
    except RuntimeError as e:
        # Surface config errors cleanly instead of a Python traceback.
        click.echo(f"Error: {redact(str(e))}", err=True)
        sys.exit(2)


if __name__ == "__main__":
    main()
