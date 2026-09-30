"""
Start the application: the FastAPI API on port 8000, which also serves the React UI at /web/.

    python run_app.py                       # then open http://127.0.0.1:8000/web/
    python run_app.py --api-port 8010

Ctrl+C stops it. The database must exist first:
    python db/seed.py && python semantics/build_catalog.py

Binding to anything other than this computer (--host 0.0.0.0 or a network address) is refused
unless APP_API_KEY is set, because the API would otherwise be open to the whole network. Even
then the React UI has no login of its own: put it behind a login proxy or keep it local.
"""

import argparse
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def wait_for(url, seconds=30):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return True
        except OSError:
            time.sleep(0.5)
    return False


def main():
    parser = argparse.ArgumentParser(description="Run the ITSM NL2SQL API and its React UI.")
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1", help="interface to bind (default local only)")
    args = parser.parse_args()

    sys.path.insert(0, str(ROOT / "agent"))
    from llm import load_env  # pyright: ignore[reportMissingImports]
    load_env()
    if args.host not in LOCAL_HOSTS:
        if not os.getenv("APP_API_KEY"):
            sys.exit(f"Refusing to listen on {args.host}: set APP_API_KEY in .env first, otherwise "
                     "anyone on the network can query the data and spend your model credit.")
        print(f"WARNING: listening on {args.host}. The API needs X-API-Key, but the React UI "
              "has no login; anyone who can reach it can use it.", flush=True)

    if not (ROOT / "db" / "tickets.sqlite").exists():
        sys.exit("db/tickets.sqlite is missing. Run: python db/seed.py && python semantics/build_catalog.py")

    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    api = subprocess.Popen([sys.executable, "-B", "-m", "uvicorn", "api.main:app", "--host", args.host,
                            "--port", str(args.api_port)], cwd=ROOT, env=env)
    if not wait_for(f"http://127.0.0.1:{args.api_port}/health"):
        api.terminate()
        sys.exit("The API did not start; see the messages above.")
    react = (f"http://127.0.0.1:{args.api_port}/web/" if (ROOT / "web" / "dist").is_dir()
             else "not built (cd web && npm install && npm run build)")
    print(f"\n  API        http://127.0.0.1:{args.api_port}/docs\n"
          f"  React UI   {react}\n"
          "  Ctrl+C to stop.\n", flush=True)
    try:
        while api.poll() is None:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        if api.poll() is None:
            api.terminate()
        try:
            api.wait(timeout=10)
        except subprocess.TimeoutExpired:
            api.kill()


if __name__ == "__main__":
    main()
