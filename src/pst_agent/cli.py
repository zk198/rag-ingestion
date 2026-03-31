from __future__ import annotations

import argparse
import json

from .config import Settings
from .service import AgentService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pst-agent", description="Ingest PST and related files for AI retrieval")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest = subparsers.add_parser("ingest", help="Ingest one or more files or directories")
    ingest.add_argument("paths", nargs="+", help="Files or directories to ingest")
    ingest.add_argument("--source-name", default="default")
    ingest.add_argument("--rebuild", action="store_true")
    ingest.add_argument("--account-email", default=None, help="Email address of the source account")
    ingest.add_argument("--account-type", default="other", choices=["work", "private", "other"], help="Account category")
    ingest.add_argument("--display-name", default=None, help="Human-readable label for the source")
    ingest.add_argument("--description", default=None, help="Free-text description of the source")

    search = subparsers.add_parser("search", help="Search indexed content")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--source-name", default=None)

    subparsers.add_parser("stats", help="Show index statistics")
    subparsers.add_parser("sources", help="List indexed sources")

    get_message = subparsers.add_parser("get-message", help="Fetch a message by id")
    get_message.add_argument("message_id")

    get_document = subparsers.add_parser("get-document", help="Fetch a document by id")
    get_document.add_argument("document_id")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    service = AgentService(Settings.from_env())

    if args.command == "ingest":
        result = service.ingest_paths(
            paths=args.paths,
            source_name=args.source_name,
            rebuild=args.rebuild,
            account_email=args.account_email,
            account_type=args.account_type,
            display_name=args.display_name,
            description=args.description,
        )
    elif args.command == "search":
        result = service.search(query=args.query, limit=args.limit, source_name=args.source_name)
    elif args.command == "stats":
        result = service.stats()
    elif args.command == "sources":
        result = service.list_sources()
    elif args.command == "get-message":
        result = service.get_message(args.message_id)
    elif args.command == "get-document":
        result = service.get_document(args.document_id)
    else:  # pragma: no cover
        parser.error("unknown command")
        return

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
