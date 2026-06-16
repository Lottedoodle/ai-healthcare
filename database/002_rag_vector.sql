-- =============================================================================
-- RAG migration: pgvector + PDF ingest + vector search
-- รันหลัง schema.sql บน Supabase SQL Editor
-- เปิด extension ก่อน: Dashboard → Database → Extensions → vector
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS vector;

-- เก็บ path ไฟล์ PDF ต้นฉบับ (Supabase Storage)
ALTER TABLE medical_knowledge_documents
    ADD COLUMN IF NOT EXISTS storage_path TEXT,
    ADD COLUMN IF NOT EXISTS file_name TEXT,
    ADD COLUMN IF NOT EXISTS ingest_status TEXT NOT NULL DEFAULT 'ready'
        CHECK (ingest_status IN ('pending', 'processing', 'ready', 'failed')),
    ADD COLUMN IF NOT EXISTS uploaded_by UUID REFERENCES auth.users (id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS error_message TEXT;

-- embedding อยู่ที่ chunk — Cohere Embed Multilingual v3 = 1024 dims
ALTER TABLE medical_knowledge_chunks
    ADD COLUMN IF NOT EXISTS embedding vector(1024);

CREATE INDEX IF NOT EXISTS idx_med_knowledge_chunks_embedding
    ON medical_knowledge_chunks
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- =============================================================================
-- Vector search RPC (backend/agent เรียกผ่าน SQL)
-- =============================================================================
CREATE OR REPLACE FUNCTION match_medical_chunks(
    query_embedding vector(1024),
    match_count int DEFAULT 5,
    match_threshold float DEFAULT 0.3
)
RETURNS TABLE (
    chunk_id uuid,
    document_id uuid,
    document_title text,
    content text,
    similarity float
)
LANGUAGE sql STABLE
AS $$
    SELECT
        c.id AS chunk_id,
        c.document_id,
        d.title AS document_title,
        c.content,
        1 - (c.embedding <=> query_embedding) AS similarity
    FROM medical_knowledge_chunks c
    JOIN medical_knowledge_documents d ON d.id = c.document_id
    WHERE d.is_active = true
      AND d.ingest_status = 'ready'
      AND c.embedding IS NOT NULL
      AND 1 - (c.embedding <=> query_embedding) >= match_threshold
    ORDER BY c.embedding <=> query_embedding
    LIMIT match_count;
$$;

-- Supabase Storage bucket (สร้าง manual ใน Dashboard หรือรันด้านล่างถ้าใช้ได้)
-- INSERT INTO storage.buckets (id, name, public) VALUES ('medical-docs', 'medical-docs', false)
-- ON CONFLICT DO NOTHING;
