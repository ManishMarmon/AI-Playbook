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
_load_keyvault_secrets(_KV_URL)

MPACT_OAUTH_URL     = os.environ["MPACT_OAUTH_URL"]
MPACT_CLIENT_ID     = os.environ["MPACT_CLIENT_ID"]
MPACT_CLIENT_SECRET = os.environ["MPACT_CLIENT_SECRET"]

COBBLESTONE_BASE_URL = "https://marmon.cobblestone.software/api2/CSSAPI/V2"
REQUEST_GET_URL      = f"{COBBLESTONE_BASE_URL}/ContractExternalRequest/Get"
REQUEST_FILE_GET_URL = f"{COBBLESTONE_BASE_URL}/ContractFilesExt/Get"

OUTPUT_DIR = Path(__file__).parent / "output"

# u_RequestProcessStatus values, carried over from requestAnalytics_v2's
# SKIP_STATUS_EXECUTED / SKIP_STATUS_NOT_EXECUTED (that project used them to
# skip execution-detection LLM calls). Here they're only a tag, not a filter —
# "Advice Only" requests may still contain real negotiated redlines worth
# seeing, so dropping them silently would lose data; let the catalog surface
# the tag and leave the call to a human.
PROCESS_STATUS_CONTRACT_EXISTS = {"Contract Created", "Executed; awaiting contract creation"}
PROCESS_STATUS_NO_CONTRACT = {"Advice Only", "Request Cancelled"}
