"""Run all four local FastAPI processes; stop them together with Ctrl+C."""
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.common.config import app_origin  # noqa: E402


def main():
    app_origin()
    from services.common.database import connect
    for setting in ("IDENTITY_DATABASE_URL", "CUSTOMERS_DATABASE_URL", "WORKSHOP_DATABASE_URL"):
        try:
            with connect(os.getenv(setting, "")) as database:
                database.execute("SELECT 1")
        except Exception:
            raise SystemExit(f"PostgreSQL is unavailable for {setting}. Configure .env and start PostgreSQL first.")
    if len(os.getenv("INTERNAL_SERVICE_TOKEN", "")) < 32:
        raise SystemExit("Configure INTERNAL_SERVICE_TOKEN with at least 32 characters in .env")
    host = os.getenv("API_HOST", "127.0.0.1")
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("The local launcher binds internal services to loopback; use Docker for deployment")
    entries = [("identity_service", 8003), ("customer_service", 8001), ("workshop_service", 8002),
               ("api_gateway", int(os.getenv("API_PORT", "8000")))]
    for _, port in entries:
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError as error:
                raise SystemExit(f"Port {port} is already in use. Stop its existing server first.") from error
    children = []
    def stop(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        for service, port in entries:
            children.append(subprocess.Popen([sys.executable, "-m", "uvicorn", f"services.{service}.app:app",
                "--host", "127.0.0.1", "--port", str(port), "--no-proxy-headers"], cwd=ROOT))
        print(f"FastAPI: http://127.0.0.1:{entries[-1][1]}/docs", flush=True)
        while all(child.poll() is None for child in children):
            time.sleep(0.25)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    raise SystemExit(main())
