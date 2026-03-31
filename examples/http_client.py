from __future__ import annotations

import httpx

BASE_URL = "http://localhost:8000"


def main() -> None:
    with httpx.Client(base_url=BASE_URL, timeout=300.0) as client:
        ingest = client.post(
            "/ingest",
            json={
                "paths": ["/data/inbox"],
                "source_name": "demo",
                "rebuild": True,
            },
        )
        ingest.raise_for_status()
        print("INGEST", ingest.json())

        search = client.post(
            "/search",
            json={
                "query": "invoice contract amendment",
                "limit": 5,
                "source_name": "demo",
            },
        )
        search.raise_for_status()
        print("SEARCH", search.json())


if __name__ == "__main__":
    main()
