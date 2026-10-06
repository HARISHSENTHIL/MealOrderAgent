"""Multi-user storage: encrypted OAuth tokens, order history, preferences.

SQLAlchemy Core so the same code runs on SQLite (local) and Postgres (server).
Per Swiggy's data policy we store food data only - no phone numbers or addresses.
"""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet
from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

STATE_DIR = Path(os.environ.get("FOODORDER_HOME", Path.home() / ".foodorder"))
STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
DB_URL = os.environ.get("FOODORDER_DB_URL", f"sqlite:///{STATE_DIR / 'foodorder.db'}")

DISPLAY_TZ = ZoneInfo("Asia/Kolkata")

metadata = MetaData()

users = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("external_ref", String(128), unique=True, nullable=False),  # "cli:local", "tg:12345"
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

# Extra identities that resolve to an existing user, e.g. "tg:12345" -> the CLI user after /pair.
user_aliases = Table(
    "user_aliases",
    metadata,
    Column("alias", String(128), primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
)

oauth_tokens = Table(
    "oauth_tokens",
    metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("provider", String(32), primary_key=True),
    Column("tokens_enc", Text),
    Column("client_info_enc", Text),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), onupdate=func.now()),
)

orders = Table(
    "orders",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("provider", String(32), nullable=False),
    Column("provider_order_id", String(64), nullable=False),
    Column("restaurant_id", String(64)),
    Column("restaurant_name", String(256)),
    Column("cuisines", String(256)),
    Column("ordered_at", DateTime(timezone=True)),
    Column("total", Float),
    Column("item_total", Float),
    Column("delivery_fee", Float),
    Column("discount", Float),
    Column("coupon", String(64)),
    Column("payment_method", String(32)),
    Column("status", String(64)),
    Column("source", String(16), nullable=False),  # "import" | "agent"
    Column("reorder_items", Text),  # JSON: exact ids/variants/addons to rebuild the cart
    UniqueConstraint("user_id", "provider", "provider_order_id"),
)

order_items = Table(
    "order_items",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("order_id", Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
    Column("name", String(256), nullable=False),
    Column("quantity", Float),
    Column("price", Float),
    Column("is_veg", Integer),
)

preferences = Table(
    "preferences",
    metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("key", String(64), primary_key=True),
    Column("value", Text, nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), onupdate=func.now()),
)

# Per-user daily message counter: a public bot must cap Claude spend per user.
usage = Table(
    "usage",
    metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("day", String(10), primary_key=True),  # YYYY-MM-DD (IST)
    Column("messages", Integer, nullable=False, default=0),
)

_is_postgres = DB_URL.startswith("postgresql")
engine = create_engine(
    DB_URL,
    future=True,
    pool_pre_ping=_is_postgres,  # survive Postgres restarts in a long-running bot
    # We write naive UTC datetimes (see _utc); make Postgres interpret them as UTC, not the
    # server's local timezone (IST on this Mac), or every order time shifts by 5h30.
    connect_args={"options": "-c timezone=UTC"} if _is_postgres else {},
)
metadata.create_all(engine)
if engine.dialect.name == "sqlite" and engine.url.database:
    Path(engine.url.database).chmod(0o600)  # order history is personal data


def _upsert(table: Table):
    return (pg_insert if engine.dialect.name == "postgresql" else sqlite_insert)(table)


# ---------- encryption ----------

def _fernet() -> Fernet:
    key = os.environ.get("FOODORDER_SECRET_KEY")
    if not key:
        key_path = STATE_DIR / "secret.key"
        if not key_path.exists():
            key_path.write_bytes(Fernet.generate_key())
            key_path.chmod(0o600)
        key = key_path.read_bytes().decode()
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(text: str) -> str:
    return _fernet().encrypt(text.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


# ---------- users ----------

def find_user(external_ref: str) -> int | None:
    with engine.connect() as conn:
        alias = conn.execute(select(user_aliases.c.user_id).where(user_aliases.c.alias == external_ref)).first()
        if alias:
            return alias.user_id
        row = conn.execute(select(users.c.id).where(users.c.external_ref == external_ref)).first()
        return row.id if row else None


def link_alias(alias: str, user_id: int) -> None:
    stmt = _upsert(user_aliases).values(alias=alias, user_id=user_id)
    with engine.begin() as conn:
        conn.execute(stmt.on_conflict_do_update(index_elements=["alias"], set_={"user_id": user_id}))


def get_or_create_user(external_ref: str) -> int:
    if (uid := find_user(external_ref)) is not None:
        return uid
    with engine.begin() as conn:
        row = conn.execute(select(users.c.id).where(users.c.external_ref == external_ref)).first()
        if row:
            return row.id
        return conn.execute(users.insert().values(external_ref=external_ref)).inserted_primary_key[0]


# ---------- tokens ----------

def load_token_field(user_id: int, provider: str, field: str) -> str | None:
    with engine.connect() as conn:
        row = conn.execute(
            select(oauth_tokens.c[field]).where(
                oauth_tokens.c.user_id == user_id, oauth_tokens.c.provider == provider
            )
        ).first()
    return decrypt(row[0]) if row and row[0] else None


def save_token_field(user_id: int, provider: str, field: str, value: str | None) -> None:
    enc = encrypt(value) if value is not None else None
    stmt = _upsert(oauth_tokens).values(user_id=user_id, provider=provider, **{field: enc})
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "provider"], set_={field: enc, "updated_at": func.now()}
    )
    with engine.begin() as conn:
        conn.execute(stmt)


def logged_in_providers(user_id: int) -> list[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            select(oauth_tokens.c.provider).where(
                oauth_tokens.c.user_id == user_id, oauth_tokens.c.tokens_enc.is_not(None)
            )
        ).all()
    return sorted(r.provider for r in rows)


# ---------- orders ----------

def _num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace("₹", "").replace(",", "").strip())
    except ValueError:
        return None


def _utc(dt: datetime | None) -> datetime | None:
    """Store naive UTC: SQLite drops tz info, so normalise before writing."""
    if dt is None:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).replace(tzinfo=None)


def _display_time(dt: datetime | None) -> str | None:
    return dt.replace(tzinfo=timezone.utc).astimezone(DISPLAY_TZ).strftime("%Y-%m-%d %H:%M IST") if dt else None


def save_order(user_id: int, provider: str, order: dict, items: list[dict], source: str) -> bool:
    """Insert or refresh an order. Returns True if it was new."""
    values = {
        "restaurant_id": order.get("restaurant_id"),
        "restaurant_name": order.get("restaurant_name"),
        "cuisines": order.get("cuisines"),
        "ordered_at": _utc(order.get("ordered_at")),
        "total": _num(order.get("total")),
        "item_total": _num(order.get("item_total")),
        "delivery_fee": _num(order.get("delivery_fee")),
        "discount": _num(order.get("discount")),
        "coupon": order.get("coupon"),
        "payment_method": order.get("payment_method"),
        "status": order.get("status"),
        "reorder_items": json.dumps(order["reorder_items"]) if order.get("reorder_items") else None,
    }
    values = {k: v for k, v in values.items() if v is not None}
    key = dict(user_id=user_id, provider=provider, provider_order_id=str(order["provider_order_id"]))
    with engine.begin() as conn:
        existing = conn.execute(
            select(orders.c.id).where(*(orders.c[k] == v for k, v in key.items()))
        ).first()
        if existing:
            if values:
                conn.execute(orders.update().where(orders.c.id == existing.id).values(**values))
            order_id, is_new = existing.id, False
        else:
            order_id = conn.execute(orders.insert().values(**key, source=source, **values)).inserted_primary_key[0]
            is_new = True
        if items:
            conn.execute(order_items.delete().where(order_items.c.order_id == order_id))
            conn.execute(
                order_items.insert(),
                [
                    {
                        "order_id": order_id,
                        "name": i["name"],
                        "quantity": _num(i.get("quantity")) or 1,
                        "price": _num(i.get("price")),
                        "is_veg": i.get("is_veg"),
                    }
                    for i in items
                    if i.get("name")
                ],
            )
    return is_new


def search_orders(user_id: int, text: str | None = None, provider: str | None = None, limit: int = 10) -> list[dict]:
    q = select(orders).where(orders.c.user_id == user_id)
    if provider:
        q = q.where(orders.c.provider == provider)
    if text:
        like = f"%{text.lower()}%"
        item_match = select(order_items.c.order_id).where(func.lower(order_items.c.name).like(like))
        q = q.where(
            (func.lower(orders.c.restaurant_name).like(like))
            | (func.lower(orders.c.cuisines).like(like))
            | (orders.c.id.in_(item_match))
        )
    q = q.order_by(orders.c.ordered_at.desc().nulls_last()).limit(limit)
    with engine.connect() as conn:
        rows = [dict(r._mapping) for r in conn.execute(q)]
        for r in rows:
            r["items"] = [
                f"{int(i.quantity or 1)} x {i.name}"
                for i in conn.execute(select(order_items).where(order_items.c.order_id == r["id"]))
            ]
            r["reorder_items"] = json.loads(r["reorder_items"]) if r["reorder_items"] else None
            r["ordered_at"] = _display_time(r["ordered_at"])
            del r["user_id"]
    return rows


def spending(user_id: int, days: int) -> dict:
    since = _utc(datetime.now(timezone.utc) - timedelta(days=days))
    with engine.connect() as conn:
        rows = conn.execute(
            select(orders.c.provider, func.count(), func.coalesce(func.sum(orders.c.total), 0))
            .where(orders.c.user_id == user_id, orders.c.ordered_at >= since)
            .group_by(orders.c.provider)
        ).all()
    by_provider = {p: {"orders": n, "spent": round(s, 2)} for p, n, s in rows}
    return {
        "days": days,
        "total_spent": round(sum(v["spent"] for v in by_provider.values()), 2),
        "total_orders": sum(v["orders"] for v in by_provider.values()),
        "by_provider": by_provider,
    }


def top_dishes(user_id: int, limit: int = 10) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            select(order_items.c.name, orders.c.restaurant_name, orders.c.provider, func.count().label("n"))
            .join(orders, orders.c.id == order_items.c.order_id)
            .where(orders.c.user_id == user_id)
            .group_by(order_items.c.name, orders.c.restaurant_name, orders.c.provider)
            .order_by(func.count().desc())
            .limit(limit)
        ).all()
    return [{"dish": r.name, "restaurant": r.restaurant_name, "provider": r.provider, "times": r.n} for r in rows]


# ---------- preferences ----------

def set_preference(user_id: int, key: str, value: str) -> None:
    stmt = _upsert(preferences).values(user_id=user_id, key=key, value=value)
    stmt = stmt.on_conflict_do_update(index_elements=["user_id", "key"], set_={"value": value, "updated_at": func.now()})
    with engine.begin() as conn:
        conn.execute(stmt)


def delete_preference(user_id: int, key: str) -> bool:
    with engine.begin() as conn:
        res = conn.execute(preferences.delete().where(preferences.c.user_id == user_id, preferences.c.key == key))
    return res.rowcount > 0


def get_preferences(user_id: int) -> dict[str, str]:
    with engine.connect() as conn:
        rows = conn.execute(select(preferences.c.key, preferences.c.value).where(preferences.c.user_id == user_id))
        return {r.key: r.value for r in rows}


def delete_user_data(user_id: int) -> None:
    """Right-to-erasure: wipe everything we hold for a user."""
    with engine.begin() as conn:
        ids = select(orders.c.id).where(orders.c.user_id == user_id)
        conn.execute(order_items.delete().where(order_items.c.order_id.in_(ids)))
        for t in (orders, preferences, oauth_tokens, user_aliases, usage):
            conn.execute(t.delete().where(t.c.user_id == user_id))


# ---------- usage ----------

def _today_ist() -> str:
    return datetime.now(DISPLAY_TZ).strftime("%Y-%m-%d")


def count_message(user_id: int) -> int:
    """Increment and return today's message count for the user."""
    day = _today_ist()
    stmt = _upsert(usage).values(user_id=user_id, day=day, messages=1)
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "day"], set_={"messages": usage.c.messages + 1}
    )
    with engine.begin() as conn:
        conn.execute(stmt)
        return conn.execute(
            select(usage.c.messages).where(usage.c.user_id == user_id, usage.c.day == day)
        ).scalar_one()


# ---------- telegram identities / nudges ----------

def telegram_ids(user_id: int) -> list[int]:
    """Telegram chat ids linked to a user (own row or /pair alias)."""
    with engine.connect() as conn:
        own = conn.execute(select(users.c.external_ref).where(users.c.id == user_id)).scalars().all()
        aliases = conn.execute(select(user_aliases.c.alias).where(user_aliases.c.user_id == user_id)).scalars().all()
    return [int(ref[3:]) for ref in [*own, *aliases] if ref.startswith("tg:") and find_user(ref) == user_id]


def users_with_preference(key: str) -> list[tuple[int, str]]:
    with engine.connect() as conn:
        rows = conn.execute(select(preferences.c.user_id, preferences.c.value).where(preferences.c.key == key))
        return [(r.user_id, r.value) for r in rows]


def ordered_since(user_id: int, start: datetime) -> bool:
    with engine.connect() as conn:
        n = conn.execute(
            select(func.count()).select_from(orders).where(
                orders.c.user_id == user_id, orders.c.ordered_at >= _utc(start)
            )
        ).scalar_one()
    return n > 0
