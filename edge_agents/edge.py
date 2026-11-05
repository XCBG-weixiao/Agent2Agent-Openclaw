import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID, uuid4

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

from .common import MCP_TOOLS, PLAN
from .delegation import Directory, make_mcp
from .local_plan import FilePlan, execute, validate_paths


class Turn(BaseModel):
    session_id: UUID | None = None


class Review(Turn):
    mode: Literal["result"]
    task: str = Field(min_length=1, max_length=48_000)


class Local(Turn):
    mode: Literal["plan"]
    source: str
    report: str


Submission = Annotated[Review | Local, Field(discriminator="mode")]
STATIC = Path(__file__).with_name("static")
CHAT_PROMPT = """Answer ordinary questions and follow-ups directly using the conversation context.
When the user asks for delegation or wants a code review or test design, use discover_agents
and choose specialists by their advertised skills. If the user asks for particular specialists,
delegate to each relevant one and report any unavailable expert. Include the relevant objective
and code from the conversation, then summarize the actual results. Never invent a delegation.

User message:
"""
PLAN_PROMPT = """Use discover_agents for skill local-file-plan, then delegate_task once to a
discovered planner for that skill, omitting text. The application will validate and execute the
returned plan locally. Return a short status based on the actual tool result."""


def line(kind: str, **data) -> str:
    return json.dumps({"type": kind, **data}, ensure_ascii=False) + "\n"


async def frames(gateway_port: int, prompt: str | None = None, session_id: UUID | None = None):
    session = (session_id or uuid4()).hex
    uri = f"ws://127.0.0.1:{gateway_port}/ws/chat?agent=edge&session_id={session}"
    async with connect(uri, subprotocols=["zeroclaw.v1"], proxy=None, open_timeout=5) as ws:
        await ws.send(json.dumps({"type": "connect"}))
        async with asyncio.timeout(10):
            while True:
                event = json.loads(await ws.recv())
                if event["type"] == "error":
                    raise ValueError("ZeroClaw could not open the edge session.")
                if event["type"] == "connected":
                    break
        if prompt is None:
            return
        await ws.send(json.dumps({"type": "message", "content": prompt}))
        async for raw in ws:
            event = json.loads(raw)
            yield event
            if event["type"] in {"done", "error", "approval_request"}:
                return


def tool_output(raw) -> dict:
    data = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(data, dict):
        raise ValueError("Unexpected ZeroClaw tool result.")
    return data


def create_edge(directory: Directory, root: Path, gateway_port: int, port: int) -> FastAPI:
    mcp = make_mcp(directory)
    mcp_app = mcp.streamable_http_app(json_response=True, stateless_http=True)
    active_sessions: set[UUID] = set()

    @asynccontextmanager
    async def lifespan(app):
        async with mcp_app.router.lifespan_context(mcp_app):
            yield

    app = FastAPI(lifespan=lifespan)
    app.routes.extend(mcp_app.routes)

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        valid_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if request.headers.get("host") not in valid_hosts:
            return PlainTextResponse("Forbidden", status_code=403)
        browser_origin = request.headers.get("origin")
        if browser_origin and browser_origin not in {f"http://{host}" for host in valid_hosts}:
            return PlainTextResponse("Forbidden", status_code=403)
        return await call_next(request)

    @app.get("/")
    async def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/ready")
    async def ready():
        try:
            async for _ in frames(gateway_port):
                pass
        except (OSError, TimeoutError, WebSocketException, ValueError) as exc:
            raise HTTPException(503, "ZeroClaw is starting.") from exc
        return {"ready": True}

    @app.get("/api/connection")
    async def connection():
        try:
            async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
                response = await client.get(f"http://127.0.0.1:{gateway_port}/health")
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(503, "ZeroClaw is unavailable.") from exc
        return {"online": True}

    @app.get("/api/agents")
    async def agents():
        try:
            return await directory.discover()
        except httpx.HTTPError as exc:
            raise HTTPException(502, "无法连接 Agent 目录。") from exc

    async def run_turn(request: Submission):
        prompt = CHAT_PROMPT + request.task if request.mode == "result" else PLAN_PROMPT
        plan = None
        try:
            async with asyncio.timeout(480):
                async for event in frames(gateway_port, prompt, request.session_id):
                    kind = event["type"]
                    name = event.get("name")
                    if kind == "tool_call" and name in MCP_TOOLS:
                        args = event.get("args", {})
                        args = json.loads(args) if isinstance(args, str) else args
                        objective = args.get("text")
                        yield line(kind, name=name, id=event.get("id"),
                                   agent_id=args.get("agent_id"), skill_id=args.get("skill_id"),
                                   objective=objective[:160] if isinstance(objective, str) else None)
                    elif kind == "tool_result" and name in MCP_TOOLS:
                        output = tool_output(event["output"])
                        if (name == "edge__delegate_task" and output.get("skill_id") == PLAN
                                and "plan" in output):
                            plan = output["plan"]
                        yield line(kind, name=name, id=event.get("id"), output=output)
                    elif kind == "chunk" and request.mode == "result" and event.get("content"):
                        yield line("delta", text=event["content"])
                    elif kind == "done":
                        if request.mode == "plan":
                            if plan is None:
                                raise ValueError("远端 Agent 没有返回可执行计划。")
                            FilePlan.model_validate(plan)
                            yield line("plan_validated", plan=plan)
                            report = await asyncio.to_thread(execute, root, plan, request.source, request.report)
                            yield line("done", text=report, report_path=request.report)
                        else:
                            yield line("done", text=event["full_response"])
                        return
                    elif kind in {"error", "approval_request"}:
                        raise ValueError("ZeroClaw 未完成本次任务。请检查模型连接和工具配置。")
            raise ValueError("ZeroClaw 连接已结束。")
        except (OSError, TimeoutError, WebSocketException, ValueError, KeyError) as exc:
            message = str(exc) if isinstance(exc, (ValueError, FileExistsError)) else type(exc).__name__
            yield line("error", message=message)

    async def run(request: Submission):
        session_id = request.session_id
        if session_id in active_sessions:
            yield line("error", message="这段对话仍有一轮任务在运行。")
            return
        if session_id:
            active_sessions.add(session_id)
        try:
            async for event in run_turn(request):
                yield event
        finally:
            if session_id:
                active_sessions.discard(session_id)

    @app.post("/api/runs")
    async def submit(request: Submission):
        if request.mode == "plan":
            try:
                validate_paths(root, request.source, request.report)
            except (OSError, ValueError) as exc:
                raise HTTPException(422, str(exc)) from exc
        return StreamingResponse(run(request), media_type="application/x-ndjson")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
