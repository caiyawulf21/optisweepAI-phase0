from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
from http.client import HTTPConnection
from pathlib import Path


BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8000"))
STREAMLIT_HOST = "0.0.0.0"
STREAMLIT_PORT = int(os.getenv("PORT", os.getenv("STREAMLIT_SERVER_PORT", "8501")))
BACKEND_HEALTH_PATH = "/health"
BACKEND_URL = f"http://{BACKEND_HOST}:{BACKEND_PORT}"


def _configure_logging() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _python_executable() -> str:
    try:
        import uvicorn  # noqa: F401
    except ImportError:
        for candidate in (
            Path("/antenv/bin/python"),
            Path("/opt/venv/bin/python"),
            Path("/app/.venv/bin/python"),
        ):
            if candidate.exists():
                return str(candidate)
    return sys.executable


def _prepare_runtime() -> Path:
    root = _repo_root()
    os.chdir(root)
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    existing = os.environ.get("PYTHONPATH", "")
    parts = [part for part in existing.split(os.pathsep) if part]
    if root_str not in parts:
        os.environ["PYTHONPATH"] = (
            root_str if not parts else root_str + os.pathsep + existing
        )
    os.environ.setdefault("API_BASE_URL", BACKEND_URL)
    os.environ.setdefault("STREAMLIT_SERVER_HEADLESS", "true")
    os.environ.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")
    os.environ.setdefault("STREAMLIT_SERVER_ADDRESS", STREAMLIT_HOST)
    os.environ.setdefault("STREAMLIT_SERVER_PORT", str(STREAMLIT_PORT))
    return root


def _start_process(name: str, command: list[str], cwd: Path) -> subprocess.Popen:
    logging.info("starting_%s command=%s cwd=%s", name, " ".join(command), cwd)
    return subprocess.Popen(command, cwd=str(cwd), env=os.environ.copy())


def _backend_healthy() -> bool:
    conn: HTTPConnection | None = None
    try:
        conn = HTTPConnection(BACKEND_HOST, BACKEND_PORT, timeout=2)
        conn.request("GET", BACKEND_HEALTH_PATH)
        response = conn.getresponse()
        response.read()
        return 200 <= response.status < 500
    except OSError:
        return False
    finally:
        if conn is not None:
            conn.close()


def _wait_for_backend(process: subprocess.Popen, timeout_seconds: int = 120) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        exit_code = process.poll()
        if exit_code is not None:
            raise RuntimeError(f"FastAPI exited before health check passed: {exit_code}")
        if _backend_healthy():
            logging.info("backend_health_ok url=%s%s", BACKEND_URL, BACKEND_HEALTH_PATH)
            return
        time.sleep(1)
    raise RuntimeError(
        f"FastAPI did not become healthy within {timeout_seconds} seconds"
    )


def _terminate(processes: list[subprocess.Popen]) -> None:
    for process in processes:
        if process.poll() is None:
            process.terminate()
    deadline = time.monotonic() + 10
    for process in processes:
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.2)
        if process.poll() is None:
            process.kill()


def main() -> int:
    _configure_logging()
    root = _prepare_runtime()
    python_exe = _python_executable()
    logging.info(
        "container_entrypoint root=%s python=%s streamlit_port=%s backend_port=%s",
        root,
        python_exe,
        STREAMLIT_PORT,
        BACKEND_PORT,
    )

    backend = _start_process(
        "fastapi",
        [
            python_exe,
            "-m",
            "uvicorn",
            "backend.app.main:app",
            "--host",
            BACKEND_HOST,
            "--port",
            str(BACKEND_PORT),
        ],
        root,
    )
    processes = [backend]

    def handle_signal(signum: int, _frame: object) -> None:
        logging.info("shutdown_signal signal=%s", signum)
        _terminate(processes)
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    try:
        _wait_for_backend(backend)
        streamlit = _start_process(
            "streamlit",
            [
                python_exe,
                "-m",
                "streamlit",
                "run",
                "ui/Home.py",
                "--server.address",
                STREAMLIT_HOST,
                "--server.port",
                str(STREAMLIT_PORT),
            ],
            root,
        )
        processes.append(streamlit)

        while True:
            for name, process in (("fastapi", backend), ("streamlit", streamlit)):
                exit_code = process.poll()
                if exit_code is not None:
                    logging.error("process_exited name=%s exit_code=%s", name, exit_code)
                    _terminate(processes)
                    return int(exit_code) if exit_code else 1
            time.sleep(2)
    except Exception:
        logging.exception("container_startup_failed")
        _terminate(processes)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
