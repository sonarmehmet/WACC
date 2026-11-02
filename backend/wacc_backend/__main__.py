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
    uvicorn.run(create_app(settings, user_token=user_token), host=settings.host, port=settings.port,
                log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
