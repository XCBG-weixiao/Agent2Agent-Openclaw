import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import uvicorn

from .common import origin, required


def edge_config(port: int, gateway_port: int, directory: Path) -> str:
    return f"""
schema_version = 3

[gateway]
host = "127.0.0.1"
port = {gateway_port}
require_pairing = false

[providers.models.custom.default]
uri = {json.dumps(required("EDGE_MODEL_URL"), ensure_ascii=False)}
model = {json.dumps(required("EDGE_MODEL"), ensure_ascii=False)}
native_tools = true

[agents.edge]
model_provider = "custom.default"
risk_profile = "edge"
mcp_bundles = ["edge"]

[agents.edge.workspace]
path = {json.dumps(str(directory), ensure_ascii=False)}

[[mcp.servers]]
name = "edge"
transport = "http"
url = "http://127.0.0.1:{port}/mcp"
tool_timeout_secs = 200

[mcp_bundles.edge]
servers = ["edge"]

[risk_profiles.edge]
level = "supervised"
allowed_tools = ["edge__discover_agents", "edge__delegate_task"]
auto_approve = ["edge__discover_agents", "edge__delegate_task"]
"""


def run_edge(args, token: str) -> None:
    from .delegation import Directory
    from .edge import create_edge

    binary = shutil.which(os.environ.get("ZEROCLAW_BIN", "zeroclaw"))
    if not binary:
        raise ValueError("Install ZeroClaw 0.8.7 or set ZEROCLAW_BIN.")
    required("EDGE_MODEL_API_KEY")
    root = args.workspace.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("The local workspace must be a directory.")
    origins = {origin(item.strip()) for item in required("AGENT_ALLOWED_ORIGINS").split(",")}
    directory = Directory(required("AGENT_REGISTRY_URL"), token, origins)
    app = create_edge(directory, root, args.gateway_port, args.port)
    state = (args.state_dir or Path(".edge-state") / f"gateway-{args.gateway_port}").resolve()
    state.mkdir(parents=True, exist_ok=True)
    (state / "config.toml").write_text(edge_config(args.port, args.gateway_port, state), encoding="utf-8")
    # The child needs only its own model credentials, not the registry token.
    env = {key: value for key, value in os.environ.items()
           if key not in {"AGENT_PLATFORM_TOKEN", "DSH_MODEL_API_KEY", "AGENTSCOPE_MODEL_API_KEY",
                          "EDGE_MODEL_API_KEY"}}
    env["ZEROCLAW_providers__models__custom__default__api_key"] = required("EDGE_MODEL_API_KEY")
    with subprocess.Popen([binary, "--config-dir", str(state), "gateway"], env=env) as gateway:
        try:
            uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)
        finally:
            if gateway.poll() is None:
                gateway.terminate()
                try:
                    gateway.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    gateway.kill()


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m edge_agents")
    commands = parser.add_subparsers(dest="command", required=True)
    registry = commands.add_parser("registry")
    registry.add_argument("--host", default="127.0.0.1")
    registry.add_argument("--port", type=int, default=8310)
    worker = commands.add_parser("worker")
    worker.add_argument("kind", choices=["codex", "dsh", "agentscope"])
    worker.add_argument("--host", default="127.0.0.1")
    worker.add_argument("--port", required=True, type=int)
    worker.add_argument("--public-url", required=True)
    worker.add_argument("--id")
    edge = commands.add_parser("edge")
    edge.add_argument("--workspace", required=True, type=Path)
    edge.add_argument("--port", type=int, default=8300)
    edge.add_argument("--gateway-port", type=int, default=8301)
    edge.add_argument("--state-dir", type=Path, help="ZeroClaw state directory for conversation history.")
    args = parser.parse_args()
    try:
        token = required("AGENT_PLATFORM_TOKEN")
        if args.command == "edge":
            run_edge(args, token)
        elif args.command == "registry":
            from .registry import create_registry
            uvicorn.run(create_registry(token), host=args.host, port=args.port, access_log=False)
        else:
            from .worker import create_card, create_worker, make_runner
            registry_url = required("AGENT_REGISTRY_URL")
            origin(registry_url)
            app = create_worker(args.kind, create_card(args.kind, args.public_url), token,
                                make_runner(args.kind), args.id or args.kind, registry_url)
            uvicorn.run(app, host=args.host, port=args.port, access_log=False)
    except (OSError, ValueError) as exc:
        sys.exit(str(exc))


if __name__ == "__main__":
    main()
