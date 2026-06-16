from __future__ import annotations

import os


def get_database_url() -> str:
    """Build Postgres URL from DATABASE_URL or PG_* vars."""
    url = os.getenv("DATABASE_URL", "").strip()
    if url:
        return url

    host = os.getenv("PG_HOST", "").strip()
    user = os.getenv("PG_USER", "").strip()
    password = os.getenv("PG_PASSWORD", "").strip()
    port = os.getenv("PG_PORT", "6543").strip()
    database = os.getenv("PG_DATABASE", "postgres").strip()

    if host and user and password:
        return f"postgresql://{user}:{password}@{host}:{port}/{database}"

    raise RuntimeError(
        "Database not configured — set DATABASE_URL or PG_HOST/PG_USER/PG_PASSWORD in .env"
    )


def supabase_rest_config() -> tuple[str, str] | None:
    """Supabase PostgREST — ใช้ service role หรือ publishable/anon key."""
    base = os.getenv("NEXT_PUBLIC_SUPABASE_URL", "").rstrip("/")
    key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        or os.getenv("SUPABASE_SECRET_KEY", "").strip()
        or os.getenv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_OR_ANON_KEY", "").strip()
        or os.getenv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", "").strip()
    )
    if base and key:
        return base, key
    return None
