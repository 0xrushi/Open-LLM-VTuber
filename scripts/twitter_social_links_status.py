#!/usr/bin/env python3
"""Print Twitter/X social_links totals by status buckets."""

import os

import psycopg
from psycopg.rows import dict_row


def main() -> None:
    url = os.environ.get(
        "DISCORD_POSTGRES_URL",
        "postgres://discord:discord@localhost:5432/discord_ingestion",
    )

    with psycopg.connect(url, row_factory=dict_row) as conn:
        total = conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM social_links
            WHERE lower(platform) IN ('twitter', 'x')
            """
        ).fetchone()["c"]

        rows = conn.execute(
            """
            SELECT lower(status) AS status, COUNT(*) AS c
            FROM social_links
            WHERE lower(platform) IN ('twitter', 'x')
            GROUP BY lower(status)
            """
        ).fetchall()

    by_status = {r["status"]: r["c"] for r in rows}

    pending = by_status.get("pending", 0)
    failed = by_status.get("failed", 0)
    successful = by_status.get("done", 0) + by_status.get("successful", 0)
    in_progress = (
        by_status.get("in_progress", 0)
        + by_status.get("in-progress", 0)
        + by_status.get("processing", 0)
        + by_status.get("running", 0)
    )

    print(f"total: {total}")
    print(f"pending: {pending}")
    print(f"failed: {failed}")
    print(f"successful: {successful}")
    print(f"in_progress: {in_progress}")


if __name__ == "__main__":
    main()
