from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from google.protobuf.json_format import MessageToDict, ParseError
from pydantic import BaseModel

from .common import authorized, rpc_card

HEARTBEAT_SECONDS = 5
LEASE_SECONDS = 15


@dataclass
class Entry:
    card: dict
    lease: str
    expires: float


class Registration(BaseModel):
    card: dict


class Lease(BaseModel):
    lease: str


def create_registry(token: str, clock: Callable[[], float] = monotonic) -> FastAPI:
    app = FastAPI()
    entries: dict[str, Entry] = {}

    async def authenticate(authorization: Annotated[str, Header()] = "") -> None:
        if not authorized(authorization, token):
            raise HTTPException(401, "Invalid agent platform token.")

    protected = [Depends(authenticate)]

    def online() -> dict[str, Entry]:
        now = clock()
        for agent_id in [key for key, entry in entries.items() if entry.expires <= now]:
            del entries[agent_id]
        return entries

    @app.get("/health")
    async def health():
        return {"ready": True}

    @app.put("/agents/{agent_id}", dependencies=protected)
    async def register(agent_id: str, registration: Registration):
        if agent_id in online():
            raise HTTPException(409, "Agent ID already has an active lease.")
        try:
            card = MessageToDict(rpc_card(registration.card))
        except (ParseError, ValueError) as exc:
            raise HTTPException(422, "Invalid A2A 1.0 Agent Card.") from exc
        lease = uuid4().hex
        entries[agent_id] = Entry(card, lease, clock() + LEASE_SECONDS)
        return {"lease": lease}

    @app.post("/agents/{agent_id}/heartbeat", dependencies=protected, status_code=204)
    async def heartbeat(agent_id: str, lease: Lease):
        entry = online().get(agent_id)
        if not entry or entry.lease != lease.lease:
            raise HTTPException(404, "Active lease was not found.")
        entry.expires = clock() + LEASE_SECONDS
        return Response(status_code=204)

    @app.get("/agents", dependencies=protected)
    async def discover(skill_id: str | None = None):
        return [
            {"id": agent_id, "card": entry.card}
            for agent_id, entry in sorted(online().items())
            if skill_id is None or any(skill["id"] == skill_id for skill in entry.card["skills"])
        ]

    @app.get("/agents/{agent_id}", dependencies=protected)
    async def get_agent(agent_id: str):
        entry = online().get(agent_id)
        if not entry:
            raise HTTPException(404, "Agent is offline or unknown.")
        return {"id": agent_id, "card": entry.card}

    return app
