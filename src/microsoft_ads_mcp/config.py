"""Configuration: environment variables, per-user folders and API hosts.

Everything is read from environment variables (optionally loaded from a .env
file). Local files live in a per-user folder, ~/.microsoft-ads-mcp/ by default,
so they don't depend on where the package is installed (uvx installs into a
cache):

* secrets/microsoft-ads-token.json: the refresh token (folder 0700, file 0600)
* logs/audit.jsonl: the audit log of writes (folder 0700, file 0600)
* .env: optional settings, read after ./.env
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

APP_DIR_NAME = ".microsoft-ads-mcp"
DEFAULT_TOKEN_NAME = "microsoft-ads-token.json"
DEFAULT_AUDIT_LOG_NAME = "audit.jsonl"
# "sse" (HTTP+SSE) is deprecated by the MCP spec; prefer "streamable-http".
TRANSPORTS = ("stdio", "streamable-http", "sse")
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

# Microsoft identity platform (Entra ID). "common" accepts both work or school
# accounts and personal Microsoft accounts, as Microsoft recommends for the API.
LOGIN_HOST = "https://login.microsoftonline.com"
ADS_SCOPE = "https://ads.microsoft.com/msads.manage"
SCOPE = f"{ADS_SCOPE} offline_access"
# Microsoft's documented redirect URI for public (desktop) clients.
NATIVE_REDIRECT_URI = "https://login.microsoftonline.com/common/oauth2/nativeclient"
# Microsoft publishes this universal developer token for the sandbox only.
SANDBOX_DEVELOPER_TOKEN = "BBD37VB98"

API_VERSION = "v13"
ENVIRONMENTS = ("production", "sandbox")
# REST path prefix (first path segment) -> service host label.
SERVICE_HOSTS = {
    "CampaignManagement": "campaign",
    "CustomerManagement": "clientcenter",
    "CustomerBilling": "clientcenter",
    "Reporting": "reporting",
    "AdInsight": "adinsight",
    "Bulk": "bulk",
}


def service_base_url(service: str, environment: str) -> str:
    """Base URL for a REST service prefix such as 'CampaignManagement'."""
    label = SERVICE_HOSTS.get(service)
    if label is None:
        raise ValueError(
            f"Unknown Microsoft Advertising service '{service}'. "
            f"Known: {', '.join(sorted(SERVICE_HOSTS))}."
        )
    sandbox = ".sandbox" if environment == "sandbox" else ""
    return f"https://{label}.api{sandbox}.bingads.microsoft.com"


def api_hosts(environment: str) -> list[str]:
    """Every API host the server may call in this environment."""
    return sorted({service_base_url(s, environment) for s in SERVICE_HOSTS})


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def parse_tool_groups(raw: str | None) -> list[str]:
    """Split a comma-separated MICROSOFT_ADS_TOOL_GROUPS value and check every name.

    Names are case-insensitive and may use '-' for '_'. Empty means all groups.
    """
    from .tools import resolve_tool_groups  # local: tools imports this module

    names = [p.strip().lower().replace("-", "_") for p in (raw or "").split(",")]
    names = [n for n in names if n]
    return resolve_tool_groups(names) if names else []


@dataclass
class Config:
    client_id: str
    developer_token: str
    refresh_token: str | None
    audit_log: Path
    client_secret: str | None = None
    environment: str = "production"
    tenant: str = "common"
    customer_id: str | None = None
    account_id: str | None = None
    token_file: Path | None = None
    # True when the refresh token came from MICROSOFT_ADS_REFRESH_TOKEN rather than the file.
    refresh_token_from_env: bool = False
    timeout: float = 60.0
    dry_run: bool = False
    log_level: str = "INFO"
    transport: str = "stdio"
    host: str = "127.0.0.1"
    port: int = 8000
    allow_remote: bool = False
    # Tool modules to register; empty means all (see microsoft_ads_mcp.tools.TOOL_GROUPS).
    tool_groups: list[str] = field(default_factory=list)
    # Register only tools annotated read-only (plus the meta tools).
    read_only: bool = False
    # Writes touching more than this many entities need confirm='APPLY'.
    bulk_threshold: int = 10
    # Bid or budget increases above this percentage need confirm='APPLY'.
    max_increase_pct: float = 20.0
    # Optional absolute caps; values above them need confirm='APPLY'.
    max_daily_budget: float | None = None
    max_bid: float | None = None
    # Audit entries older than this are pruned at startup; 0 keeps them.
    audit_retention_days: int = 30
    # Report and bulk downloads larger than this are refused.
    max_download_mb: int = 200

    @property
    def token_url(self) -> str:
        return f"{LOGIN_HOST}/{self.tenant}/oauth2/v2.0/token"

    @property
    def authorize_url(self) -> str:
        return f"{LOGIN_HOST}/{self.tenant}/oauth2/v2.0/authorize"

    def base_url(self, service: str) -> str:
        return service_base_url(service, self.environment)


def app_home() -> Path:
    """The per-user folder (MICROSOFT_ADS_HOME, default ~/.microsoft-ads-mcp)."""
    raw = os.environ.get("MICROSOFT_ADS_HOME", "").strip()
    return Path(raw).expanduser().resolve() if raw else Path.home() / APP_DIR_NAME


def ensure_private_dir(path: Path) -> Path:
    """Create a folder (and parents) readable only by the owner (0700 on POSIX)."""
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix":
        os.chmod(path, 0o700)
    return path


def _path_or_none(raw: str | None) -> Path | None:
    if not raw or not raw.strip():
        return None
    return Path(raw).expanduser().resolve()


def token_file_path() -> Path:
    """Where `microsoft-ads-mcp auth` stores the refresh token."""
    return _path_or_none(os.environ.get("MICROSOFT_ADS_TOKEN_FILE")) or (
        app_home() / "secrets" / DEFAULT_TOKEN_NAME
    )


def audit_log_path() -> Path:
    """The audit log location (MICROSOFT_ADS_AUDIT_LOG, default ~/.microsoft-ads-mcp/logs/audit.jsonl)."""
    return _path_or_none(os.environ.get("MICROSOFT_ADS_AUDIT_LOG")) or (
        app_home() / "logs" / DEFAULT_AUDIT_LOG_NAME
    )


def load_env(env_file: Path | None = None) -> None:
    """Load settings from --env, else ./.env and then ~/.microsoft-ads-mcp/.env.

    Variables already set in the environment always win.
    """
    if env_file is not None:
        load_dotenv(dotenv_path=env_file, override=False)
        return
    load_dotenv(dotenv_path=Path.cwd() / ".env", override=False)
    home_env = app_home() / ".env"
    if home_env.is_file():
        load_dotenv(dotenv_path=home_env, override=False)


def read_token_file(path: Path) -> str | None:
    """Return the refresh token stored by `microsoft-ads-mcp auth`, or None."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise RuntimeError(f"Could not read the token file {path}: {e}") from e
    token = data.get("refresh_token") if isinstance(data, dict) else None
    return token or None


def _numeric_id(name: str) -> str | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    if not raw.isdigit():
        raise RuntimeError(f"{name} must be a numeric ID, got '{raw}'.")
    return raw


def _float_or_none(name: str) -> float | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError as e:
        raise RuntimeError(f"{name} must be a number, got '{raw}'") from e


def load_config(env_file: Path | None = None, *, require_refresh_token: bool = True) -> Config:
    """Read configuration from the environment (and optional .env files).

    Raises RuntimeError with actionable messages on misconfiguration."""
    load_env(env_file)

    client_id = os.environ.get("MICROSOFT_ADS_CLIENT_ID", "").strip()
    if not client_id:
        raise RuntimeError(
            "MICROSOFT_ADS_CLIENT_ID must be set.\n"
            "  - It is the Application (client) ID of your app registration in the Azure\n"
            "    portal (Microsoft Entra ID -> App registrations), a GUID like\n"
            "    00001111-aaaa-2222-bbbb-3333cccc4444. See docs/setup-microsoft-ads-api.md."
        )

    environment = os.environ.get("MICROSOFT_ADS_ENVIRONMENT", "production").strip().lower()
    environment = environment or "production"
    if environment not in ENVIRONMENTS:
        raise RuntimeError(
            f"MICROSOFT_ADS_ENVIRONMENT must be production or sandbox, got '{environment}'."
        )

    developer_token = os.environ.get("MICROSOFT_ADS_DEVELOPER_TOKEN", "").strip()
    if not developer_token:
        if environment == "sandbox":
            developer_token = SANDBOX_DEVELOPER_TOKEN
        else:
            raise RuntimeError(
                "MICROSOFT_ADS_DEVELOPER_TOKEN must be set for production.\n"
                "  - A Super Admin requests it in Microsoft Advertising under\n"
                "    Settings -> Developer settings (https://ads.microsoft.com/cc/Settings/DevSettings).\n"
                "  - For the sandbox, set MICROSOFT_ADS_ENVIRONMENT=sandbox instead."
            )

    tenant = os.environ.get("MICROSOFT_ADS_TENANT", "common").strip() or "common"
    if not all(c.isalnum() or c in "-." for c in tenant):
        raise RuntimeError(f"MICROSOFT_ADS_TENANT has invalid characters: '{tenant}'.")

    token_file = token_file_path()
    refresh_token = os.environ.get("MICROSOFT_ADS_REFRESH_TOKEN", "").strip() or None
    if refresh_token is None:
        refresh_token = read_token_file(token_file)
    if refresh_token is None and require_refresh_token:
        raise RuntimeError(
            "No refresh token configured. Either:\n"
            "  - run `microsoft-ads-mcp auth` once (saves it to "
            f"{token_file}), or\n"
            "  - set MICROSOFT_ADS_REFRESH_TOKEN, or\n"
            "  - set MICROSOFT_ADS_TOKEN_FILE to the file `microsoft-ads-mcp auth` wrote."
        )

    transport = os.environ.get("MICROSOFT_ADS_TRANSPORT", "stdio").strip().lower()
    if transport not in TRANSPORTS:
        raise RuntimeError(
            f"MICROSOFT_ADS_TRANSPORT must be one of {', '.join(TRANSPORTS)}, got '{transport}'."
        )

    def _int(name: str, default: str) -> int:
        try:
            return int(os.environ.get(name, default))
        except ValueError as e:
            raise RuntimeError(f"{name} must be an integer") from e

    def _float(name: str, default: str) -> float:
        try:
            return float(os.environ.get(name, default))
        except ValueError as e:
            raise RuntimeError(f"{name} must be a number") from e

    return Config(
        client_id=client_id,
        client_secret=os.environ.get("MICROSOFT_ADS_CLIENT_SECRET", "").strip() or None,
        developer_token=developer_token,
        refresh_token=refresh_token,
        environment=environment,
        tenant=tenant,
        customer_id=_numeric_id("MICROSOFT_ADS_CUSTOMER_ID"),
        account_id=_numeric_id("MICROSOFT_ADS_ACCOUNT_ID"),
        audit_log=audit_log_path(),
        token_file=token_file,
        refresh_token_from_env=bool(os.environ.get("MICROSOFT_ADS_REFRESH_TOKEN", "").strip()),
        timeout=_float("MICROSOFT_ADS_TIMEOUT", "60"),
        dry_run=_truthy(os.environ.get("MICROSOFT_ADS_DRY_RUN")),
        log_level=os.environ.get("MICROSOFT_ADS_LOG_LEVEL", "INFO").upper(),
        transport=transport,
        host=os.environ.get("MICROSOFT_ADS_HOST", "127.0.0.1"),
        port=_int("MICROSOFT_ADS_PORT", "8000"),
        allow_remote=_truthy(os.environ.get("MICROSOFT_ADS_ALLOW_REMOTE")),
        tool_groups=parse_tool_groups(os.environ.get("MICROSOFT_ADS_TOOL_GROUPS")),
        read_only=_truthy(os.environ.get("MICROSOFT_ADS_READ_ONLY")),
        bulk_threshold=_int("MICROSOFT_ADS_BULK_THRESHOLD", "10"),
        max_increase_pct=_float("MICROSOFT_ADS_MAX_INCREASE_PCT", "20"),
        max_daily_budget=_float_or_none("MICROSOFT_ADS_MAX_DAILY_BUDGET"),
        max_bid=_float_or_none("MICROSOFT_ADS_MAX_BID"),
        audit_retention_days=_int("MICROSOFT_ADS_AUDIT_RETENTION_DAYS", "30"),
        max_download_mb=_int("MICROSOFT_ADS_MAX_DOWNLOAD_MB", "200"),
    )
