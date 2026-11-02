import os
import sys

from .config import ROOT, load_env_file, load_settings


def main() -> int:
    import uvicorn
    from .app import create_app
    from .security import get_or_create_user_token

    load_env_file(ROOT / "data" / "llm.env")  # optional, git-ignored: local/cloud model settings
    settings = load_settings()
    if settings.host not in ("127.0.0.1", "localhost"):
        print("WARNING: binding beyond localhost. Use a firewall/VPN; the token is the only protection.",
              file=sys.stderr)
    user_token = get_or_create_user_token(settings)
    print(f"[WACC] Agent token file: {settings.token_file}")
    print("[WACC] ONAY TOKEN'I (yalniz sen kullan, kimseyle/hicbir ajanla paylasma; diske yazilmaz):")
    print(f"       {user_token}")
    app = create_app(settings, user_token=user_token)
    worker = None
    if os.environ.get("WACC_WORKER", "1") == "1":
        from .worker import Worker, register_builtin_handlers
        register_builtin_handlers(app.state.engine, app.state.orchestrator, app.state.execution)
        worker = Worker(app.state.engine)
        worker.start()
        print("[WACC] Is isleyici (worker) acik: ai.complete ve exec.run isleri calisir. Kapatmak: WACC_WORKER=0")
    try:
        uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")
    finally:
        if worker:
            worker.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
