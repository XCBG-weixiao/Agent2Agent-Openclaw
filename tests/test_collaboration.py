import asyncio
import json
import socket
from contextlib import asynccontextmanager
from copy import deepcopy
from uuid import uuid4

import httpx
import pytest
import uvicorn
from google.protobuf.json_format import MessageToDict

from edge_agents.common import PLAN, REVIEW
from edge_agents.delegation import Directory
from edge_agents.edge import create_edge
from edge_agents.local_plan import execute
from edge_agents.registry import create_registry
from edge_agents.worker import create_card, create_worker

TOKEN = "test-platform-token"
PLAN_DATA = {
    "version": "1",
    "steps": [
        {"action": "scan_text_files", "source": "source_directory"},
        {"action": "write_markdown_report", "target": "report_path"},
    ],
}


@asynccontextmanager
async def server(build):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        url = f"http://127.0.0.1:{listener.getsockname()[1]}"
        app = build(url)
        service = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="on"))
        task = asyncio.create_task(service.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(5):
                while not service.started:
                    await asyncio.sleep(.01)
            yield url
        finally:
            service.should_exit = True
            await task


async def test_discovery_a2a_and_expiry():
    now = [10.0]
    registry = create_registry(TOKEN, clock=lambda: now[0])
    observed = []

    async def run(skill, text):
        observed.append((skill, text))
        if skill == PLAN:
            return PLAN_DATA
        raise RuntimeError("test provider failure")

    async with server(lambda _: registry) as registry_url:
        async with server(lambda url: create_worker(
            "agentscope", create_card("agentscope", f"{url}/a2a"), TOKEN, run,
            "agentscope-test", registry_url,
        )) as worker_url:
            directory = Directory(registry_url, TOKEN, {worker_url})
            assert await directory.discover(REVIEW) == []
            assert [x["id"] for x in await directory.discover(PLAN)] == ["agentscope-test"]
            result = await directory.delegate("agentscope-test", PLAN, None)
            assert result["task_id"]
            assert result["plan"] == PLAN_DATA
            assert observed[0][0] == PLAN
            with pytest.raises(ValueError, match="no text or local paths"):
                await directory.delegate("agentscope-test", PLAN, "local/secret")
            with pytest.raises(ValueError, match="TASK_STATE_FAILED"):
                await directory.delegate("agentscope-test", "test-design", "def foo(): pass")
            now[0] += 15
            assert await directory.discover(PLAN) == []
            with pytest.raises(ValueError, match="offline"):
                await directory.delegate("agentscope-test", PLAN, None)


async def test_lease_can_only_be_renewed_by_its_owner():
    now = [0.0]
    app = create_registry(TOKEN, clock=lambda: now[0])
    headers = {"Authorization": f"Bearer {TOKEN}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        card = MessageToDict(create_card("codex", "http://127.0.0.1:8311/a2a"))
        response = await client.put("/agents/codex", headers=headers, json={"card": card})
        lease = response.json()
        now[0] = 10
        assert (await client.post("/agents/codex/heartbeat", headers=headers, json={"lease": "other"})).status_code == 404
        assert (await client.post("/agents/codex/heartbeat", headers=headers, json=lease)).status_code == 204
        assert (await client.get("/agents")).status_code == 401
        now[0] = 18
        assert (await client.get("/agents/codex", headers=headers)).status_code == 200
        now[0] = 25
        assert (await client.get("/agents/codex", headers=headers)).status_code == 404


def test_plan_executes_locally_without_overwriting(tmp_path):
    (tmp_path / "input.txt").write_text("one\ntwo\n", encoding="utf-8")
    content = execute(tmp_path, PLAN_DATA, ".", "report.md")
    assert "| input.txt | 2 |" in content
    assert (tmp_path / "report.md").read_text(encoding="utf-8") == content
    with pytest.raises(FileExistsError):
        execute(tmp_path, PLAN_DATA, ".", "report.md")


def test_invalid_plan_and_paths_are_rejected_before_write(tmp_path):
    invalid = deepcopy(PLAN_DATA)
    invalid["steps"][1]["action"] = "shell"
    with pytest.raises(ValueError):
        execute(tmp_path, invalid, ".", "report.md")
    with pytest.raises(ValueError, match="outside the workspace"):
        execute(tmp_path, PLAN_DATA, ".", "../report.md")
    assert not list(tmp_path.iterdir())


async def test_edge_executes_a_tool_plan_without_sending_paths(monkeypatch, tmp_path):
    from edge_agents import edge

    async def gateway(port, prompt, session_id):
        assert "private-source" not in prompt
        assert "private-report.md" not in prompt
        yield {
            "type": "tool_result",
            "name": "edge__delegate_task",
            "output": json.dumps({"skill_id": PLAN, "plan": PLAN_DATA}),
        }
        yield {"type": "done"}

    monkeypatch.setattr(edge, "frames", gateway)
    source = tmp_path / "private-source"
    source.mkdir()
    (source / "data.txt").write_text("first\nsecond\n", encoding="utf-8")
    app = create_edge(Directory("http://127.0.0.1:8310", TOKEN, set()), tmp_path, 8301, 8300)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8300",
    ) as client:
        response = await client.post("/api/runs", json={
            "mode": "plan", "source": "private-source", "report": "private-report.md",
        })
    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines()]
    assert [event["type"] for event in events] == ["tool_result", "plan_validated", "done"]
    assert "| data.txt | 2 |" in (tmp_path / "private-report.md").read_text(encoding="utf-8")


async def test_chat_keeps_the_session_and_relays_live_events(monkeypatch, tmp_path):
    from edge_agents import edge

    session = uuid4()
    seen = []

    async def gateway(port, prompt, session_id):
        seen.append((prompt, session_id))
        yield {"type": "tool_call", "name": "edge__delegate_task", "id": "delegate",
               "args": {"agent_id": "dsh", "skill_id": REVIEW, "text": "Check an empty list"}}
        yield {"type": "chunk", "content": "Review"}
        yield {"type": "done", "full_response": "Review complete."}

    monkeypatch.setattr(edge, "frames", gateway)
    app = create_edge(Directory("http://127.0.0.1:8310", TOKEN, set()), tmp_path, 8301, 8300)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8300",
    ) as client:
        for prompt in ("Review my function.", "What about empty input?"):
            response = await client.post("/api/runs", json={
                "mode": "result", "task": prompt, "session_id": str(session),
            })
            events = [json.loads(line) for line in response.text.splitlines()]
            assert [event["type"] for event in events] == ["tool_call", "delta", "done"]
            assert events[0]["objective"] == "Check an empty list"
            assert events[-1]["text"] == "Review complete."

    assert [sid for _, sid in seen] == [session, session]
    assert seen[1][0].endswith("What about empty input?")
