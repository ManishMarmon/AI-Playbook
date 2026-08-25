"""
Redline Discovery Engine — config.

Every environment-specific value (Key Vault URL, the Key Vault secret NAMES
this project reads, the CobbleStone API base URL) is loaded from a local,
gitignored .env at the repo root — never hardcoded here. This isn't just
credential hygiene: this project's repo has been public, and even secret
*names* and internal API endpoints are real reconnaissance material for
whoever finds it, per the project's own audit findings. Copy .env.example to
.env and fill in the real values (ask a teammate who already has them, or
pull them from Key Vault directly) before running anything that touches
CobbleStone, Key Vault, or Postgres.
"""

import os
from pathlib import Path

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass


def _load_dotenv_once() -> None:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")


def _require_env(attr: str, hint: str) -> str:
    val = os.getenv(attr)
    if not val:
        raise RuntimeError(f"{attr} not set — copy .env.example to .env and fill in {hint}.")
    return val


def _load_keyvault_secrets(vault_url: str) -> None:
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient

    kv = SecretClient(vault_url=vault_url, credential=DefaultAzureCredential())
    secret_map = {
        "MPACT_OAUTH_URL":     _require_env("MPACT_OAUTH_URL_SECRET_NAME", "the Key Vault secret name for the MPact OAuth URL"),
        "MPACT_CLIENT_ID":     _require_env("MPACT_CLIENT_ID_SECRET_NAME", "the Key Vault secret name for the MPact client id"),
        "MPACT_CLIENT_SECRET": _require_env("MPACT_CLIENT_SECRET_SECRET_NAME", "the Key Vault secret name for the MPact client secret"),
    }
    for env_var, secret_name in secret_map.items():
        if not os.getenv(env_var):
            os.environ[env_var] = kv.get_secret(secret_name).value


_KV_URL_ATTRS = ("AZURE_KEY_VAULT_URL",)
_kv_url_loaded = False


def _ensure_kv_url() -> None:
    # Split out from _ensure_mpact_credentials so other Key-Vault-backed
    # clients (llm_azure.py's Azure OpenAI client) can get just the vault
    # URL from one place, without pulling in MPact-specific secret names.
    global _kv_url_loaded
    if _kv_url_loaded:
        return
    _load_dotenv_once()
    globals()["AZURE_KEY_VAULT_URL"] = _require_env("AZURE_KEY_VAULT_URL", "your Azure Key Vault URL")
    _kv_url_loaded = True


_MPACT_ATTRS = ("MPACT_OAUTH_URL", "MPACT_CLIENT_ID", "MPACT_CLIENT_SECRET")
_mpact_loaded = False


def _ensure_mpact_credentials() -> None:
    # Loaded lazily, on first actual use, so scripts that never touch the
    # CobbleStone API (e.g. run_analytics.py, which only reads local JSON) don't
    # pay for a Key Vault round-trip — or fail if Key Vault/identity is down —
    # just because they happened to `import config`.
    global _mpact_loaded
    if _mpact_loaded:
        return
    _ensure_kv_url()
    _load_keyvault_secrets(globals()["AZURE_KEY_VAULT_URL"])
    for attr in _MPACT_ATTRS:
        globals()[attr] = os.environ[attr]
    _mpact_loaded = True


_PG_ATTRS = ("PG_HOST", "PG_PORT", "PG_DB", "PG_USER", "PG_PASSWORD")
_pg_loaded = False


def _ensure_pg_credentials() -> None:
    # Postgres is a local, dedicated dev instance (see redline_discovery/db/),
    # so its credentials live in a gitignored .env at the repo root rather
    # than Key Vault — same lazy-load-on-first-use shape as MPact above, just
    # a different source.
    global _pg_loaded
    if _pg_loaded:
        return
    _load_dotenv_once()
    for attr in _PG_ATTRS:
        globals()[attr] = _require_env(attr, "your Postgres connection details (see redline_discovery/db/setup.sql)")
    _pg_loaded = True


_COBBLESTONE_ATTRS = ("COBBLESTONE_BASE_URL", "REQUEST_GET_URL", "REQUEST_FILE_GET_URL", "FILE_DOWNLOAD_URL")
_cobblestone_loaded = False


def _ensure_cobblestone_urls() -> None:
    global _cobblestone_loaded
    if _cobblestone_loaded:
        return
    _load_dotenv_once()
    base = _require_env("COBBLESTONE_BASE_URL", "the CobbleStone API base URL")
    globals()["COBBLESTONE_BASE_URL"] = base
    globals()["REQUEST_GET_URL"] = f"{base}/ContractExternalRequest/Get"
    globals()["REQUEST_FILE_GET_URL"] = f"{base}/ContractFilesExt/Get"
    globals()["FILE_DOWNLOAD_URL"] = f"{base}/Files/ContractFilesEXt/Download"
    _cobblestone_loaded = True


def __getattr__(name: str):
    if name in _KV_URL_ATTRS:
        _ensure_kv_url()
        return globals()[name]
    if name in _MPACT_ATTRS:
        _ensure_mpact_credentials()
        return globals()[name]
    if name in _PG_ATTRS:
        _ensure_pg_credentials()
        return globals()[name]
    if name in _COBBLESTONE_ATTRS:
        _ensure_cobblestone_urls()
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


OUTPUT_DIR = Path(__file__).parent / "output"

# u_RequestProcessStatus values, carried over from requestAnalytics_v2's
# SKIP_STATUS_EXECUTED / SKIP_STATUS_NOT_EXECUTED (that project used them to
# skip execution-detection LLM calls). Here they're only a tag, not a filter —
# "Advice Only" requests may still contain real negotiated redlines worth
# seeing, so dropping them silently would lose data; let the catalog surface
# the tag and leave the call to a human.
PROCESS_STATUS_CONTRACT_EXISTS = {"Contract Created", "Executed; awaiting contract creation"}
PROCESS_STATUS_NO_CONTRACT = {"Advice Only", "Request Cancelled"}
