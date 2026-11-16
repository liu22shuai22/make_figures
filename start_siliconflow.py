import argparse
from getpass import getpass
import os
from pathlib import Path
import subprocess
import sys
import time

import uvicorn


BASE_URL = "https://api.siliconflow.cn/v1"
LEGACY_BASE_URL = "https://api.siliconflow.com/v1"
DEFAULT_MODEL = "deepseek-ai/DeepSeek-V4.1-Flash"
PROJECT_DIR = Path(__file__).resolve().parent


def python_sources():
    versions = {}
    for path in PROJECT_DIR.glob("*.py"):
        try:
            versions[path.name] = path.stat().st_mtime_ns
        except FileNotFoundError:
            continue
    return versions


def run_with_reload():
    print("已开启后端自动重载，保存项目中的 Python 文件后会自动更新。", flush=True)
    while True:
        versions = python_sources()
        server = subprocess.Popen([sys.executable, "-m", "uvicorn", "api:app", "--host", "127.0.0.1",
                                   "--port", "8000"], cwd=PROJECT_DIR)
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
                    subprocess.run(["taskkill", "/PID", str(server.pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                if server.poll() is None:
                    server.terminate()
                try:
                    server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="使用硅基流动启动 ERFlow 后端")
    parser.add_argument("--new-key", action="store_true", help="重新输入 API Key，覆盖本次启动使用的旧 Key")
    parser.add_argument("--no-reload", action="store_true", help="关闭开发时的 Python 代码自动重载")
    args = parser.parse_args()

    previous_url = os.environ.get("LLM_BASE_URL", "").strip().rstrip("/")
    reuse_config = previous_url in (BASE_URL, LEGACY_BASE_URL)
    api_key = os.environ.get("LLM_API_KEY", "").strip() if reuse_config and not args.new_key else ""
    model = os.environ.get("LLM_MODEL", "").strip() if reuse_config else ""
    if not api_key:
        api_key = getpass("请输入硅基流动 API Key：").strip()
    if not api_key:
        raise SystemExit("请输入 API Key 后再启动。")
    os.environ.update(LLM_PROVIDER="openai", LLM_BASE_URL=BASE_URL,
                      LLM_MODEL=model or DEFAULT_MODEL, LLM_API_KEY=api_key)
    if args.no_reload:
        uvicorn.run("api:app", host="127.0.0.1", port=8000)
    else:
        raise SystemExit(run_with_reload())
