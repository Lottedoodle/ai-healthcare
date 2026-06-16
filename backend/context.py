from contextvars import ContextVar

supabase_user_token: ContextVar[str | None] = ContextVar("supabase_user_token", default=None)
