import asyncio
import json
import logging
import os
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
from a2a.helpers import new_data_part, new_task, new_text_message, new_text_part
from a2a.server.agent_execution import AgentExecutor
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill, TaskState
from google.protobuf.json_format import MessageToDict
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .common import PLAN, REVIEW, TEST, authorized, http_client, origin, required
from .local_plan import FilePlan, PLAN_INSTRUCTIONS
from .registry import HEARTBEAT_SECONDS

LOG = logging.getLogger(__name__)
SKILLS = {
    "codex": {REVIEW: ("Code review", "Review a pasted code snippet for correctness.")},
    "dsh": {REVIEW: ("Independent review", "Provide a second read-only code review.")},
    "agentscope": {
        TEST: ("Test design", "Design tests for a pasted code snippet."),
        PLAN: ("Local file plan", "Plan a local UTF-8 text-file line-count report."),
    },
}


def create_card(kind: str, url: str) -> AgentCard:
    origin(url)
    return AgentCard(
        name={"codex": "Codex", "dsh": "dsh", "agentscope": "AgentScope"}[kind],
        description="Remote specialist for edge collaboration.",
        version="0.1.0",
        capabilities=AgentCapabilities(),
        supported_interfaces=[AgentInterface(url=url, protocol_binding="JSONRPC", protocol_version="1.0")],
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"] + (["application/json"] if kind == "agentscope" else []),
        skills=[
            AgentSkill(id=key, name=name, description=description, tags=[key])
            for key, (name, description) in SKILLS[kind].items()
        ],
    )


async def run_cli(args: list[str], prompt: str, cwd: str, env: dict | None = None) -> bytes:
    proc = await asyncio.create_subprocess_exec(
        *args, cwd=cwd, env=env,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _ = await proc.communicate(prompt.encode())
    except asyncio.CancelledError:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        raise
    if proc.returncode:
        raise RuntimeError(f"{Path(args[0]).name} exited with status {proc.returncode}.")
    return stdout


def make_runner(kind: str):
    if kind == "agentscope":
        from agentscope.agent import Agent
        from agentscope.credential import OpenAICredential
        from agentscope.message import Msg
        from agentscope.model import OpenAIChatModel

        model = OpenAIChatModel(
            credential=OpenAICredential(
                api_key=required("AGENTSCOPE_MODEL_API_KEY"),
                base_url=required("AGENTSCOPE_MODEL_URL"),
            ),
            model=required("AGENTSCOPE_MODEL"),
            stream=False,
        )

        async def run(skill: str, prompt: str) -> str | dict:
            instructions = PLAN_INSTRUCTIONS if skill == PLAN else (
                "Design concrete tests for the supplied code. Identify edge cases and expected outcomes."
            )
            reply = await Agent(name="specialist", system_prompt=instructions, model=model).reply(
                Msg(name="user", content=[{"type": "text", "text": prompt}], role="user"),
            )
            output = reply.get_text_content()
            if not output or not output.strip():
                raise ValueError("AgentScope returned no text.")
            if skill == PLAN:
                return FilePlan.model_validate_json(output).model_dump(mode="json")
            return output

        return run

    binary = shutil.which(os.environ.get(f"{kind.upper()}_BIN", kind))
    if binary is None:
        raise ValueError(f"Install {kind} or set {kind.upper()}_BIN.")
    if kind == "dsh":
        model_url = required("DSH_MODEL_URL")
        model_id = required("DSH_MODEL")
        model_key = required("DSH_MODEL_API_KEY")

    async def run(skill: str, prompt: str) -> str:
        with TemporaryDirectory(prefix="edge-review-") as cwd:
            message = f"Review this submitted code in read-only mode. Report findings and fixes.\n\n{prompt}"
            if kind == "codex":
                output_file = Path(cwd) / "result.txt"
                await run_cli(
                    [binary, "-a", "never", "exec", "--sandbox", "read-only",
                     "--skip-git-repo-check", "--ephemeral", "--output-last-message", str(output_file), "-"],
                    message, cwd,
                )
                output = output_file.read_text(encoding="utf-8")
            else:
                home = Path(cwd) / "dsh-home"
                profile = home / "profiles" / "headless"
                profile.mkdir(parents=True)
                patch = [
                    {"id": "llm-pi-ai", "disabled": False, "config": {"providers": {"edge-model": {
                        "api": "openai-completions", "baseURL": model_url,
                        "apiKeyEnv": "EDGE_DSH_PROVIDER_KEY", "models": [{"id": model_id}],
                    }}}},
                    {"id": "agent-default-model", "config": {"provider": "edge-model", "model": model_id}},
                ]
                (profile / "cordis.patch.yml").write_text(json.dumps(patch), encoding="utf-8")
                stdout = await run_cli(
                    [binary, "--profile", "headless", "--permission-mode", "read-only",
                     "--approval-policy", "never"],
                    message, cwd,
                    {**os.environ, "DSH_HOME": str(home), "EDGE_DSH_PROVIDER_KEY": model_key},
                )
                output = stdout.decode()
            if not output.strip():
                raise ValueError(f"{kind} returned no review.")
            return output

    return run


class Specialist(AgentExecutor):
    def __init__(self, skills: dict, run):
        self.skills = skills
        self.run = run

    async def execute(self, context, event_queue) -> None:
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await event_queue.enqueue_event(new_task(
            context.task_id, context.context_id, TaskState.TASK_STATE_SUBMITTED,
        ))
        await updater.start_work()
        try:
            skill = context.metadata.get("skill_id")
            if skill not in self.skills:
                raise ValueError("The requested skill is unavailable.")
            async with asyncio.timeout(180):
                result = await self.run(skill, context.get_user_input())
            part = new_data_part(result, "application/json") if skill == PLAN else new_text_part(result)
            await updater.add_artifact([part], name="plan" if skill == PLAN else "answer")
            await updater.complete()
        except Exception as exc:
            # Provider and CLI diagnostics can contain prompts or credentials.
            LOG.warning("Specialist failed: %s", type(exc).__name__)
            await updater.failed(new_text_message(f"Specialist failed ({type(exc).__name__})."))

    async def cancel(self, context, event_queue) -> None:
        await TaskUpdater(event_queue, context.task_id, context.context_id).cancel()


def create_worker(kind: str, card: AgentCard, token: str, run, agent_id=None, registry_url=None) -> Starlette:
    active = registry_url is None

    async def health(request: Request):
        return JSONResponse({"ready": active}, status_code=200 if active else 503)

    async def renew(client, url, lease) -> None:
        nonlocal active
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            try:
                reply = await client.post(f"{url}/heartbeat", json=lease)
                reply.raise_for_status()
            except httpx.HTTPError as exc:
                active = False
                LOG.error("Lease renewal stopped: %s", type(exc).__name__)
                return

    @asynccontextmanager
    async def lifespan(app):
        nonlocal active
        async with http_client(token) as client:
            async with asyncio.TaskGroup() as jobs:
                lease_task = None
                if registry_url:
                    url = f"{registry_url.rstrip('/')}/agents/{agent_id}"
                    reply = await client.put(url, json={"card": MessageToDict(card)})
                    reply.raise_for_status()
                    active = True
                    lease_task = jobs.create_task(renew(client, url, reply.json()))
                try:
                    yield
                finally:
                    if lease_task:
                        lease_task.cancel()

    handler = DefaultRequestHandler(Specialist(SKILLS[kind], run), InMemoryTaskStore(), card)
    app = Starlette(
        routes=[Route("/health", health), *create_agent_card_routes(card),
                *create_jsonrpc_routes(handler, rpc_url="/a2a")],
        lifespan=lifespan,
    )

    async def authenticate(request, call_next):
        if request.url.path == "/a2a":
            if not authorized(request.headers.get("Authorization", ""), token):
                return JSONResponse({"error": "Invalid agent platform token."}, status_code=401)
            if not active:
                return JSONResponse({"error": "Agent registration is inactive."}, status_code=503)
        return await call_next(request)

    app.add_middleware(BaseHTTPMiddleware, dispatch=authenticate)
    return app
