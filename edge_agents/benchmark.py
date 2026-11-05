import argparse
import json
import math
import os
import platform
import signal
import statistics
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from time import monotonic, sleep

import httpx
import psutil

MIB = 1024 * 1024


def tree_rss(pid: int) -> int:
    try:
        parent = psutil.Process(pid)
        processes = [parent, *parent.children(recursive=True)]
    except psutil.NoSuchProcess:
        return 0
    total = 0
    for process in processes:
        try:
            total += process.memory_info().rss
        except psutil.NoSuchProcess:
            pass
    return total


def wait_ready(process: subprocess.Popen, base: str) -> None:
    deadline = monotonic() + 30
    with httpx.Client(timeout=1, trust_env=False) as client:
        while process.poll() is None and monotonic() < deadline:
            try:
                if client.get(f"{base}/api/ready").is_success:
                    return
            except httpx.TransportError:
                pass
            sleep(0.025)
    raise RuntimeError("Edge did not become ready within 30 seconds.")


def standard_task(pid: int, base: str, root: Path) -> int:
    stop = Event()
    peak = tree_rss(pid)

    def sample():
        nonlocal peak
        while not stop.wait(0.025):
            peak = max(peak, tree_rss(pid))

    sampler = Thread(target=sample)
    sampler.start()
    try:
        with httpx.Client(timeout=480, trust_env=False) as client:
            with client.stream("POST", f"{base}/api/runs", json={
                "mode": "plan", "source": ".", "report": "benchmark-report.md",
            }) as response:
                response.raise_for_status()
                for raw in response.iter_lines():
                    event = json.loads(raw)
                    if event["type"] == "error":
                        raise RuntimeError(event["message"])
                    if event["type"] == "done" and (root / "benchmark-report.md").is_file():
                        return max(peak, tree_rss(pid))
        raise RuntimeError("The standard local plan did not produce a report.")
    finally:
        stop.set()
        sampler.join()


def stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        parent = psutil.Process(process.pid)
        for child in parent.children(recursive=True):
            child.kill()
        process.kill()
        process.wait()


def main():
    parser = argparse.ArgumentParser(description="Measure the edge process tree and the standard local file task.")
    parser.add_argument("--runs", type=int, default=30)
    parser.add_argument("--port", type=int, default=8400)
    parser.add_argument("--gateway-port", type=int, default=8401)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be positive")
    base = f"http://127.0.0.1:{args.port}"
    starts, memory = [], []
    with TemporaryDirectory(prefix="edge-benchmark-") as workspace:
        root = Path(workspace)
        (root / "fixture.txt").write_text("alpha\nbeta\n", encoding="utf-8")
        with (root / "process.log").open("wb") as logs:
            for index in range(args.runs):
                started = monotonic()
                process = subprocess.Popen([
                    sys.executable, "-m", "edge_agents", "edge",
                    "--workspace", workspace, "--port", str(args.port),
                    "--gateway-port", str(args.gateway_port),
                ], stdout=logs, stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0)
                try:
                    wait_ready(process, base)
                    starts.append((monotonic() - started) * 1000)
                    memory.append(tree_rss(process.pid) / MIB)
                    if index == args.runs - 1:
                        peak = standard_task(process.pid, base, root) / MIB
                finally:
                    stop_process(process)
    zero = subprocess.check_output(
        [os.environ.get("ZEROCLAW_BIN", "zeroclaw"), "--version"], text=True,
    ).strip()
    result = {
        "system": platform.platform(), "arch": platform.machine(),
        "cpu_logical": psutil.cpu_count(), "host_ram_mib": round(psutil.virtual_memory().total / MIB),
        "python": platform.python_version(), "zeroclaw": zero,
        "runs": args.runs, "memory_kind": "working_set" if os.name == "nt" else "rss",
        "cold_start_ms_p50": round(statistics.median(starts), 2),
        "cold_start_ms_p95": round(sorted(starts)[math.ceil(len(starts) * .95) - 1], 2),
        "ready_memory_mib_p50": round(statistics.median(memory), 2),
        "standard_task_peak_mib": round(peak, 2),
        "cold_start_ms_samples": [round(x, 2) for x in starts],
        "ready_memory_mib_samples": [round(x, 2) for x in memory],
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
