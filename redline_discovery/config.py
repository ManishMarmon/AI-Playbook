"""
Redline Discovery Engine — config.

Reuses the same Key Vault + MPact/CobbleStone setup as
D:\\contractAbstraction (same vault, same secret names, same base API URL)
so no new credentials need to be provisioned.
"""

import os
from pathlib import Path

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass


def _load_keyvault_secrets(vault_url: str) -> None:
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient

    kv = SecretClient(vault_url=vault_url, credential=DefaultAzureCredential())
    secret_map = {
        "MPACT_OAUTH_URL":     "MPACT-OAUTH-URL",
        "MPACT_CLIENT_ID":     "MPACT-CLIENT-ID",
        "MPACT_CLIENT_SECRET": "MPACT-CLIENT-SECRET",
    }
    for env_var, secret_name in secret_map.items():
        if not os.getenv(env_var):
            os.environ[env_var] = kv.get_secret(secret_name).value


_KV_URL = os.getenv("AZURE_KEY_VAULT_URL", "https://legaldataproducts-kvault.vault.azure.net/")

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
    _load_keyvault_secrets(_KV_URL)
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
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parent.parent / ".env")
    for attr in _PG_ATTRS:
        if not os.getenv(attr):
            raise RuntimeError(
                f"{attr} not set — copy .env.example to .env and fill in your "
                f"Postgres connection details (see redline_discovery/db/setup.sql)."
            )
        globals()[attr] = os.environ[attr]
    _pg_loaded = True


def __getattr__(name: str):
    if name in _MPACT_ATTRS:
        _ensure_mpact_credentials()
        return globals()[name]
    if name in _PG_ATTRS:
        _ensure_pg_credentials()
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


COBBLESTONE_BASE_URL = "https://marmon.cobblestone.software/api2/CSSAPI/V2"
REQUEST_GET_URL      = f"{COBBLESTONE_BASE_URL}/ContractExternalRequest/Get"
REQUEST_FILE_GET_URL = f"{COBBLESTONE_BASE_URL}/ContractFilesExt/Get"
FILE_DOWNLOAD_URL    = f"{COBBLESTONE_BASE_URL}/Files/ContractFilesEXt/Download"

OUTPUT_DIR = Path(__file__).parent / "output"

# u_RequestProcessStatus values, carried over from requestAnalytics_v2's
# SKIP_STATUS_EXECUTED / SKIP_STATUS_NOT_EXECUTED (that project used them to
# skip execution-detection LLM calls). Here they're only a tag, not a filter —
# "Advice Only" requests may still contain real negotiated redlines worth
# seeing, so dropping them silently would lose data; let the catalog surface
# the tag and leave the call to a human.
PROCESS_STATUS_CONTRACT_EXISTS = {"Contract Created", "Executed; awaiting contract creation"}
PROCESS_STATUS_NO_CONTRACT = {"Advice Only", "Request Cancelled"}
