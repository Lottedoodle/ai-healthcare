-- =============================================================================
-- Bedrock Cohere Embed Multilingual v3 → vector(1024)
-- รันหลัง 002_rag_vector.sql ถ้าเคยใช้ OpenAI 1536 มาก่อน
-- WARNING: จะลบ embedding เก่า — ต้อง re-ingest documents
-- =============================================================================

DROP INDEX IF EXISTS idx_med_knowledge_chunks_embedding;

ALTER TABLE medical_knowledge_chunks
    DROP COLUMN IF EXISTS embedding;

ALTER TABLE medical_knowledge_chunks
    ADD COLUMN embedding vector(1024);

CREATE INDEX idx_med_knowledge_chunks_embedding
    ON medical_knowledge_chunks
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

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

-- เก็บ model ที่ใช้ embed (debug / audit)
ALTER TABLE medical_knowledge_documents
    ADD COLUMN IF NOT EXISTS embedding_model TEXT;

ALTER TABLE medical_knowledge_chunks
    ADD COLUMN IF NOT EXISTS embedding_model TEXT;
