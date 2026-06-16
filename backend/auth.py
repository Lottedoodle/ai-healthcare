import os

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

security = HTTPBearer(auto_error=False)

SUPABASE_URL = os.getenv("NEXT_PUBLIC_SUPABASE_URL", "").rstrip("/")
SUPABASE_ANON_KEY = (
    os.getenv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_OR_ANON_KEY", "")
    or os.getenv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", "")
)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")

    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase auth is not configured",
        )

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={
                "Authorization": f"Bearer {credentials.credentials}",
                "apikey": SUPABASE_ANON_KEY,
            },
        )

    if response.status_code != 200:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = response.json()
    return {"id": user["id"], "email": user.get("email")}


async def get_authenticated_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict:
    """Verify JWT and bind token for Supabase RLS-aware REST calls."""
    from backend.context import supabase_user_token

    user = await get_current_user(credentials)
    if credentials and credentials.credentials:
        supabase_user_token.set(credentials.credentials)
    return user
