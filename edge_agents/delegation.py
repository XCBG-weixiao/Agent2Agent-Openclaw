import asyncio

import httpx
from a2a.client import ClientConfig, ClientFactory
from a2a.helpers import get_data_parts, get_text_parts, new_text_message
from a2a.types import Role, SendMessageConfiguration, SendMessageRequest, TaskState
from mcp.server.mcpserver import MCPServer

from .common import PLAN, REVIEW, TEST, http_client, origin, rpc_card
from .local_plan import PLAN_INSTRUCTIONS


class Directory:
    def __init__(self, url: str, token: str, allowed_origins: set[str]):
        origin(url)
        self.url = url.rstrip("/")
        self.token = token
        self.allowed_origins = allowed_origins

    async def discover(self, skill_id: str | None = None) -> list[dict]:
        async with http_client(self.token) as client:
            response = await client.get(
                f"{self.url}/agents", params={"skill_id": skill_id} if skill_id else None,
            )
            response.raise_for_status()
        visible = []
        for item in response.json():
            card = rpc_card(item["card"])
            if origin(card.supported_interfaces[0].url) in self.allowed_origins:
                visible.append({
                    "id": item["id"], "name": card.name,
                    "skills": [{"id": s.id, "description": s.description} for s in card.skills],
                })
        return visible

    async def delegate(self, agent_id: str, skill_id: str, text: str | None) -> dict:
        if not agent_id or not agent_id.isascii() or not agent_id.replace("-", "").isalnum():
            raise ValueError("Invalid agent ID.")
        if skill_id not in {REVIEW, TEST, PLAN}:
            raise ValueError("Unknown skill.")
        if skill_id == PLAN:
            if text is not None:
                raise ValueError("Plan requests accept no text or local paths.")
            text = PLAN_INSTRUCTIONS
        elif not text or not text.strip():
            raise ValueError("Provide the submitted code and review objective.")

        async with http_client(self.token) as directory:
            response = await directory.get(f"{self.url}/agents/{agent_id}")
            if response.status_code == 404:
                raise ValueError("The selected agent is offline or unknown.")
            response.raise_for_status()
        card = rpc_card(response.json()["card"])
        if origin(card.supported_interfaces[0].url) not in self.allowed_origins:
            raise ValueError("The agent endpoint is outside the configured origins.")
        if skill_id not in {skill.id for skill in card.skills}:
            raise ValueError("The agent does not publish the requested skill.")

        async with http_client(self.token, timeout=185) as transport:
            client = ClientFactory(ClientConfig(
                streaming=False, httpx_client=transport, supported_protocol_bindings=["JSONRPC"],
            )).create(card)
            request = SendMessageRequest(
                message=new_text_message(text, role=Role.ROLE_USER),
                configuration=SendMessageConfiguration(
                    return_immediately=False,
                    accepted_output_modes=["application/json" if skill_id == PLAN else "text/plain"],
                ),
                metadata={"skill_id": skill_id},
            )
            async with asyncio.timeout(190):
                async for event in client.send_message(request):
                    if event.WhichOneof("payload") != "task":
                        raise ValueError("Expected a completed A2A task.")
                    task = event.task
                    if task.status.state != TaskState.TASK_STATE_COMPLETED:
                        state = TaskState.Name(task.status.state)
                        detail = " ".join(get_text_parts(task.status.message.parts))
                        raise ValueError(f"Remote task ended in {state}. {detail}".strip())
                    parts = [part for artifact in task.artifacts for part in artifact.parts]
                    result = {"agent_id": agent_id, "skill_id": skill_id, "task_id": task.id}
                    if skill_id == PLAN:
                        plans = get_data_parts(parts)
                        if len(plans) != 1 or not isinstance(plans[0], dict):
                            raise ValueError("Expected exactly one structured plan.")
                        return {**result, "plan": plans[0]}
                    answer = "\n".join(get_text_parts(parts)).strip()
                    if not answer:
                        raise ValueError("The A2A task returned no text.")
                    return {**result, "answer": answer}
        raise ValueError("The A2A agent returned no task.")


def make_mcp(directory: Directory) -> MCPServer:
    mcp = MCPServer("edge")

    @mcp.tool()
    async def discover_agents(skill_id: str | None = None) -> dict:
        """Discover online remote agents, optionally by code-review, test-design, or local-file-plan."""
        try:
            return {"agents": await directory.discover(skill_id)}
        except httpx.HTTPError:
            return {"error": "The agent directory could not be reached."}

    @mcp.tool()
    async def delegate_task(agent_id: str, skill_id: str, text: str | None = None) -> dict:
        """Delegate to a discovered agent. For local-file-plan omit text; paths and file contents stay local."""
        try:
            result = await directory.delegate(agent_id, skill_id, text)
        except ValueError as exc:
            result = {"agent_id": agent_id, "skill_id": skill_id, "error": str(exc)}
        except Exception as exc:
            result = {
                "agent_id": agent_id, "skill_id": skill_id,
                "error": f"A2A delegation failed ({type(exc).__name__}).",
            }
        return result

    return mcp
