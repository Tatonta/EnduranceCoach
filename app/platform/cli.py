import argparse
import json

from app.platform.config import PlatformSettings
from app.platform.main import create_platform_app
from app.platform.store import PlatformStore


def main():
    parser = argparse.ArgumentParser(description="Multi-athlete Adaptive Coach API")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db", help="Explicitly initialize a separate platform database")
    sub.add_parser("schema", help="Write the OpenAPI contract to stdout without personal data")
    serve = sub.add_parser("serve")
    serve.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    if args.command == "serve":
        import uvicorn

        uvicorn.run(
            "app.platform.main:create_platform_app",
            factory=True,
            host="127.0.0.1",
            port=args.port,
            workers=1,
        )
    elif args.command == "schema":
        app = create_platform_app()
        print(json.dumps(app.openapi(), indent=2, ensure_ascii=False))
        app.state.store.close()
    else:
        store = PlatformStore(PlatformSettings())
        try:
            store.initialize()
            print("Platform schema initialized. Personal Garmin data was not imported.")
        finally:
            store.close()


if __name__ == "__main__":
    main()
