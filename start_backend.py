"""Start the ERFlow API with optional auto-reload. Model keys live in API 平台 / llm.local.json."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import time

import uvicorn

from llm_providers import clear_llm_environ


PROJECT_DIR = Path(__file__).resolve().parent


_SKIP_DIR_NAMES = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    "frontend",
    "dist",
    "build",
}


def python_sources():
    """Watch project Python files, including packages like assistant/."""
    versions = {}
    for path in PROJECT_DIR.rglob("*.py"):
        if any(part in _SKIP_DIR_NAMES for part in path.parts):
            continue
        try:
            versions[str(path.relative_to(PROJECT_DIR))] = path.stat().st_mtime_ns
        except FileNotFoundError:
            continue
    return versions


def run_with_reload():
    print("已开启后端自动重载，保存项目中的 Python 文件后会自动更新。", flush=True)
    while True:
        versions = python_sources()
        clear_llm_environ()
        server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "api:app", "--host", "127.0.0.1", "--port", "8000"],
            cwd=PROJECT_DIR,
        )
        try:
            while (status := server.poll()) is None:
                time.sleep(0.5)
                if python_sources() != versions:
                    print("检测到 Python 代码变化，正在重载后端……", flush=True)
                    break
            else:
                return status
        except KeyboardInterrupt:
            return 0
        finally:
            if server.poll() is None:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(server.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                if server.poll() is None:
                    server.terminate()
                try:
                    server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="启动 ERFlow 后端（模型请在 API 平台配置）")
    parser.add_argument("--no-reload", action="store_true", help="关闭开发时的 Python 代码自动重载")
    args = parser.parse_args()
    clear_llm_environ()
    if args.no_reload:
        uvicorn.run("api:app", host="127.0.0.1", port=8000)
    else:
        raise SystemExit(run_with_reload())
