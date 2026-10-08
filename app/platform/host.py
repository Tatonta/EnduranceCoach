"""Container entry point with bounded workers and explicit proxy trust."""

import os
from ipaddress import ip_network

import uvicorn


def main():
    workers = int(os.getenv("COACH_PLATFORM_WORKERS", "2"))
    if not 1 <= workers <= 8:
        raise ValueError("Configure between one and eight API workers")
    forwarded = os.getenv("COACH_PLATFORM_TRUSTED_PROXIES", "")
    if forwarded == "*":
        raise ValueError("Trust explicit reverse-proxy addresses, never all clients")
    for address in forwarded.split(","):
        if address.strip():
            ip_network(address.strip(), strict=False)
    uvicorn.run(
        "app.platform.main:create_platform_app",
        factory=True,
        host="0.0.0.0",
        port=8001,
        workers=workers,
        proxy_headers=bool(forwarded),
        forwarded_allow_ips=forwarded,
        access_log=False,  # Health-related URLs/identifiers do not belong in access logs.
        limit_concurrency=100,
        backlog=256,
        timeout_keep_alive=5,
        timeout_graceful_shutdown=30,
    )


if __name__ == "__main__":
    main()
