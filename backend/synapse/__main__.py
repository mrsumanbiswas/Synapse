"""Command line entry point.

    python -m synapse serve            run a node (HTTP API + P2P socket server)
    python -m synapse build-sample ... rebuild the bundled datasets from OpenAlex / arXiv
"""

from __future__ import annotations

import argparse
import logging
import sys


def _logging(level: str, node_id: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format=f"%(asctime)s %(levelname)-7s [{node_id}] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="synapse", description="Synapse node")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("serve", help="run the node (default)")
    sub.add_parser("build-sample", help="fetch the sample corpora", add_help=False)
    args, rest = parser.parse_known_args(argv)

    if args.command == "build-sample":
        from .tools.build_sample import main as build

        return build(rest)

    import uvicorn

    from .app import create_app
    from .config import Settings

    settings = Settings.from_env()
    _logging(settings.log_level, settings.node_id)
    uvicorn.run(create_app(settings), host=settings.http_host, port=settings.http_port,
                log_level=settings.log_level.lower(), proxy_headers=True, forwarded_allow_ips="*",
                log_config=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
