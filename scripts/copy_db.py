"""Copy every foodorder table from one database to another (e.g. SQLite -> Postgres).

    uv run python scripts/copy_db.py SOURCE_URL TARGET_URL

The target must be empty (tables are created if missing). IDs are preserved so foreign keys
stay valid, and Postgres id sequences are advanced past the copied rows. Encrypted tokens are
copied as-is, so keep the same secret key (~/.foodorder/secret.key or FOODORDER_SECRET_KEY).
"""

import sys

from sqlalchemy import create_engine, func, select, text

from foodorder.core.db import metadata


def main(source_url: str, target_url: str) -> None:
    src = create_engine(source_url)
    is_pg = target_url.startswith("postgresql")
    dst = create_engine(target_url, connect_args={"options": "-c timezone=UTC"} if is_pg else {})
    metadata.create_all(dst)

    with dst.connect() as conn:
        existing = {t.name: conn.execute(select(func.count()).select_from(t)).scalar_one() for t in metadata.sorted_tables}
    if any(existing.values()):
        raise SystemExit(f"Target is not empty: {existing}. Refusing to overwrite.")

    with src.connect() as s, dst.begin() as d:
        for table in metadata.sorted_tables:  # parents before children (FK order)
            rows = [dict(r._mapping) for r in s.execute(select(table))]
            if rows:
                d.execute(table.insert(), rows)
            print(f"{table.name}: {len(rows)} rows")
        if is_pg:
            for table in metadata.sorted_tables:
                if "id" in table.c and table.c.id.autoincrement and table.c.id.primary_key:
                    d.execute(text(
                        f"SELECT setval(pg_get_serial_sequence('{table.name}', 'id'), "
                        f"COALESCE((SELECT MAX(id) FROM {table.name}), 0) + 1, false)"
                    ))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2])
