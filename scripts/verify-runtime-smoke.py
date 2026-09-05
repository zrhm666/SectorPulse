"""Exercise the built SPA and real API using an isolated Fixture runtime.

Default: temporary SQLite. For PostgreSQL pass --postgres and set SECTOR_PULSE_TEST_DATABASE_URL
to a dedicated database whose name ends in _test; business URLs are rejected.
"""

import argparse
import json
import os
import re
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))


def verify() -> None:
    os.chdir(ROOT)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres", action="store_true")
    args = parser.parse_args()
    url = os.environ.get("SECTOR_PULSE_TEST_DATABASE_URL", "") if args.postgres else ""
    if args.postgres and not url:
        raise ValueError("--postgres requires SECTOR_PULSE_TEST_DATABASE_URL")
    if url and not urlsplit(url).path.rstrip("/").endswith("_test"):
        raise ValueError("A dedicated PostgreSQL database ending in _test is required")
    os.environ["SECTOR_PULSE_DATABASE_URL"] = url
    os.environ["SECTOR_PULSE_LLM_PROVIDER"] = "fixture"
    os.environ["SECTOR_PULSE_SCHEDULER_ENABLED"] = "false"
    from sector_pulse.web.app import create_app

    (ROOT / ".tmp").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="runtime-smoke-", dir=ROOT / ".tmp") as temp:
        sqlite_path = Path(temp) / "smoke.db"
        app = create_app() if url else create_app(database_path=sqlite_path)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
            worker = threading.Thread(
                target=server.run, kwargs={"sockets": [listener]}, daemon=True,
            )
            worker.start()
            try:
                deadline = time.monotonic() + 15
                while not server.started:
                    if not worker.is_alive() or time.monotonic() >= deadline:
                        raise RuntimeError("isolated API server did not start")
                    time.sleep(0.05)
                base = f"http://127.0.0.1:{listener.getsockname()[1]}"
                with httpx.Client(base_url=base, timeout=15, trust_env=False) as client:
                    def request(method, path, **kwargs):
                        response = client.request(method, path, **kwargs)
                        response.raise_for_status()
                        return response

                    html = request("GET", "/").text
                    assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', html)
                    assert assets, "built SPA assets missing"
                    for asset in assets:
                        request("GET", asset)
                    summary = request("GET", "/api/operations/summary").json()
                    assert summary["database"]["backend"] == ("postgresql" if url else "sqlite")
                    fixture = request("GET", "/api/fixture-input").json()
                    run_id = request("POST", "/api/runs", json={
                        "input_json": fixture, "provider": "fixture",
                    }).json()["run_id"]

                    def wait_run(identifier):
                        deadline = time.monotonic() + 30
                        while True:
                            detail = request("GET", f"/api/runs/{identifier}").json()
                            if detail["status"] != "RUNNING":
                                assert detail["status"] == "READY_FOR_HUMAN_REVIEW", (
                                    detail["status"]
                                )
                                return detail
                            if time.monotonic() >= deadline:
                                raise TimeoutError("Fixture generation did not finish")
                            time.sleep(0.1)

                    detail = wait_run(run_id)
                    assert request("GET", f"/api/runs/{run_id}/draft").json()["versions"]
                    assert request("GET", f"/api/runs/{run_id}/review").json()["decision"] == "PASS"
                    draft_id = detail["draft_id"]
                    request("POST", f"/api/runs/{run_id}/drafts/{draft_id}/approve")
                    assert request("GET", f"/api/runs/{run_id}/draft.md").text.strip()
                    audit = request("GET", f"/api/runs/{run_id}/drafts/{draft_id}/audit").json()
                    assert audit, "approval audit missing"
                    retry = request("POST", f"/api/runs/{run_id}/retry").json()["run_id"]
                    assert wait_run(retry)["retry_of_run_id"] == run_id
                    print(json.dumps({
                        "backend": summary["database"]["backend"], "result": "passed",
                        "checks": ["built SPA assets", "real HTTP API", "fixture generation",
                                   "review", "approval", "export", "audit", "retry lineage"],
                    }))
            finally:
                server.should_exit = True
                worker.join(timeout=15)
                if worker.is_alive():
                    raise RuntimeError("isolated API server did not stop")


if __name__ == "__main__":
    verify()
