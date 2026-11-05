import hmac
import os
from urllib.parse import urlsplit

import httpx
from a2a.types import AgentCard
from google.protobuf.json_format import ParseDict

GENERAL = "general-assistance"
REVIEW = "code-review"
TEST = "test-design"
PLAN = "local-file-plan"
MCP_TOOLS = {"edge__discover_agents", "edge__delegate_task"}


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"Set {name} before starting this service.")
    return value


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def authorized(value: str, token: str) -> bool:
    return hmac.compare_digest(value.encode(), bearer(token)["Authorization"].encode())


def origin(url: str) -> str:
    parsed = urlsplit(url)
    if not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("Invalid service URL.")
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "::1", "localhost"}
    ):
        raise ValueError("Use HTTPS for network services and HTTP only on loopback.")
    return f"{parsed.scheme}://{parsed.netloc.lower()}"


def rpc_card(data: dict) -> AgentCard:
    card = ParseDict(data, AgentCard())
    interfaces = list(card.supported_interfaces)
    if len(interfaces) != 1 or (
        interfaces[0].protocol_binding,
        interfaces[0].protocol_version,
    ) != ("JSONRPC", "1.0"):
        raise ValueError("Expected one A2A 1.0 JSON-RPC interface.")
    origin(interfaces[0].url)
    skill_ids = [skill.id for skill in card.skills]
    if not card.name or not skill_ids or "" in skill_ids or len(set(skill_ids)) != len(skill_ids):
        raise ValueError("Expected a named agent and distinct skill IDs.")
    return card


def http_client(token: str, timeout: float = 5) -> httpx.AsyncClient:
    return httpx.AsyncClient(headers=bearer(token), timeout=timeout, trust_env=False)
