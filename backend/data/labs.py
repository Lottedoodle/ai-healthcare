from __future__ import annotations

import re
from typing import Any

import httpx
import psycopg
from psycopg.rows import dict_row

from backend.data.db import get_database_url, supabase_rest_config
from backend.context import supabase_user_token


def _normalize_hn(hn: str) -> str:
    digits = re.sub(r"\D", "", hn.strip())
    return digits or hn.strip()


def _format_rows(hn: str, rows: list[dict[str, Any]]) -> str:
    if not rows:
        return f"ไม่พบผล lab สำหรับ HN {hn} ในระบบ"

    lines = [f"ผล lab ล่าสุดสำหรับ HN {hn}:\n"]
    for row in rows:
        code = row.get("test_code", "")
        name = row.get("test_name") or code
        if row.get("value_text"):
            value = row["value_text"]
        elif row.get("value_numeric") is not None:
            value = str(row["value_numeric"])
        else:
            value = "—"
        unit = row.get("unit") or ""
        flag = row.get("flag") or ""
        collected = row.get("collected_at")
        ref = ""
        if row.get("ref_low") is not None and row.get("ref_high") is not None:
            ref = f" (ref {row['ref_low']}-{row['ref_high']})"
        elif row.get("ref_low") is not None:
            ref = f" (ref ≥ {row['ref_low']})"

        flag_tag = f" [{flag}]" if flag else ""
        lines.append(f"- {name} ({code}): {value} {unit}{ref}{flag_tag} @ {collected}")

    return "\n".join(lines)


def _fetch_via_postgres(hn: str, *, limit: int) -> list[dict[str, Any]]:
    sql = """
        SELECT test_code, test_name, value_numeric, value_text, unit,
               ref_low, ref_high, flag, collected_at
        FROM lab_results
        WHERE hn = %s
        ORDER BY collected_at DESC
        LIMIT %s
    """
    with psycopg.connect(get_database_url(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (hn, limit))
            return list(cur.fetchall())


def _fetch_via_supabase_rest(hn: str, *, limit: int) -> list[dict[str, Any]]:
    cfg = supabase_rest_config()
    if not cfg:
        raise RuntimeError("Supabase REST not configured")

    base, key = cfg
    url = f"{base}/rest/v1/lab_results"
    params = {
        "hn": f"eq.{hn}",
        "order": "collected_at.desc",
        "limit": str(limit),
        "select": "test_code,test_name,value_numeric,value_text,unit,ref_low,ref_high,flag,collected_at",
    }
    # ใช้ JWT ของ user ที่ login → role authenticated → ผ่าน RLS lab_results
    user_jwt = supabase_user_token.get()
    auth_token = user_jwt if user_jwt else key
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {auth_token}",
    }

    with httpx.Client(timeout=15.0) as client:
        response = client.get(url, params=params, headers=headers)
        response.raise_for_status()
        return response.json()


def fetch_lab_results(hn: str, *, limit: int = 20) -> str:
    """Query lab_results — Supabase REST ก่อน (ใช้ key ใน .env) แล้วค่อย Postgres direct."""
    hn = _normalize_hn(hn)
    if not hn:
        return "ไม่พบ HN ที่ถูกต้อง"

    errors: list[str] = []

    # REST มักใช้ได้ทันทีด้วย publishable key (ไม่ต้องรอ DATABASE_URL password)
    try:
        rows = _fetch_via_supabase_rest(hn, limit=limit)
        return _format_rows(hn, rows)
    except Exception as exc:
        errors.append(f"Supabase REST: {exc}")

    try:
        rows = _fetch_via_postgres(hn, limit=limit)
        return _format_rows(hn, rows)
    except Exception as exc:
        errors.append(f"Postgres: {exc}")

    return (
        "[DB error] ไม่สามารถดึง lab ได้\n"
        + "\n".join(f"- {e}" for e in errors)
    )
