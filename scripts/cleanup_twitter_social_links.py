#!/usr/bin/env python3
"""Delete pending/failed Twitter/X entries from discord_ingestion.social_links."""

import os

import psycopg
from psycopg.rows import dict_row


def main() -> None:
    url = os.environ.get(
        "DISCORD_POSTGRES_URL",
        "postgres://discord:discord@localhost:5432/discord_ingestion",
    )

    with psycopg.connect(url, row_factory=dict_row) as conn:
        with conn.transaction():
            before = conn.execute(
                """
                SELECT status, COUNT(*) AS c
                FROM social_links
                WHERE lower(platform) IN ('twitter', 'x')
                GROUP BY status
                ORDER BY status
                """
            ).fetchall()

            deleted = conn.execute(
                """
                DELETE FROM social_links
                WHERE lower(platform) IN ('twitter', 'x')
                  AND status IN ('pending', 'failed')
                RETURNING id, status
                """
            ).fetchall()

            after = conn.execute(
                """
                SELECT status, COUNT(*) AS c
                FROM social_links
                WHERE lower(platform) IN ('twitter', 'x')
                GROUP BY status
                ORDER BY status
                """
            ).fetchall()

    print("Before:")
    if before:
        for row in before:
            print(f"  {row['status']}: {row['c']}")
    else:
        print("  (none)")

    print(f"Deleted: {len(deleted)}")

    print("After:")
    if after:
        for row in after:
            print(f"  {row['status']}: {row['c']}")
    else:
        print("  (none)")


if __name__ == "__main__":
    main()
