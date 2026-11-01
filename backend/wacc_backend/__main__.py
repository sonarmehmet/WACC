import sys

from .config import load_settings


def main() -> int:
    import uvicorn
    from .app import create_app

    settings = load_settings()
    if settings.host not in ("127.0.0.1", "localhost"):
        print("WARNING: binding beyond localhost. Use a firewall/VPN; the token is the only protection.",
              file=sys.stderr)
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
