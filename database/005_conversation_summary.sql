-- Rolling conversation summary (ChatGPT/Claude-style context compression)
ALTER TABLE chat_sessions
    ADD COLUMN IF NOT EXISTS conversation_summary TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS summary_message_count INT NOT NULL DEFAULT 0;

COMMENT ON COLUMN chat_sessions.conversation_summary IS
    'Rolling LLM summary of older messages — injected into agent context to save tokens.';
COMMENT ON COLUMN chat_sessions.summary_message_count IS
    'Number of chat_messages (from start) already folded into conversation_summary.';
