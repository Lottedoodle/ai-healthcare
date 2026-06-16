-- =============================================================================
-- Medical AI — PostgreSQL schema (Supabase-compatible)
-- รันใน Supabase SQL Editor หรือ psql
-- =============================================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
-- สำหรับ RAG / semantic search บน medical knowledge (เปิดใน Supabase Dashboard ก่อน)
-- CREATE EXTENSION IF NOT EXISTS "vector";

-- =============================================================================
-- 1) Patients (optional master — lab อ้าง HN)
-- =============================================================================
CREATE TABLE IF NOT EXISTS patients (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    hn              VARCHAR(20) NOT NULL UNIQUE,          -- Hospital Number e.g. 123456
    full_name       TEXT,
    date_of_birth   DATE,
    sex             VARCHAR(10),                          -- M / F / other
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_patients_hn ON patients (hn);

-- =============================================================================
-- 2) Chat sessions
-- =============================================================================
CREATE TABLE IF NOT EXISTS chat_sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
    title           TEXT NOT NULL DEFAULT 'New chat',
    -- LangGraph state สำหรับ multi-turn (intent, missing fields, patient_hn, ...)
    agent_state     JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- สรุปข้อความเก่า (rolling summary) เพื่อลด token ตอนส่ง context เข้า LLM
    conversation_summary   TEXT NOT NULL DEFAULT '',
    summary_message_count  INT NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_updated
    ON chat_sessions (user_id, updated_at DESC);

-- =============================================================================
-- 3) Chat history (messages)
-- =============================================================================
CREATE TABLE IF NOT EXISTS chat_messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES chat_sessions (id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content         TEXT NOT NULL,
    -- metadata จาก agent: intent, route_mode, audit_log, ...
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session_created
    ON chat_messages (session_id, created_at ASC);

-- =============================================================================
-- 4) Lab results
-- =============================================================================
CREATE TABLE IF NOT EXISTS lab_results (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      UUID REFERENCES patients (id) ON DELETE SET NULL,
    hn              VARCHAR(20) NOT NULL,                 -- denormalized สำหรับ query เร็ว
    test_code       VARCHAR(50) NOT NULL,                 -- e.g. Hb, Cr, eGFR, Na, K
    test_name       TEXT,                                 -- e.g. Hemoglobin
    value_numeric   NUMERIC(12, 4),
    value_text      TEXT,                                 -- กรณีผลเป็น text เช่น "Negative"
    unit            VARCHAR(30),                          -- g/dL, mg/dL, mL/min/1.73m2
    ref_low         NUMERIC(12, 4),
    ref_high        NUMERIC(12, 4),
    ref_text        TEXT,                                 -- e.g. "Negative"
    flag            VARCHAR(10),                          -- L / H / N / critical
    collected_at    TIMESTAMPTZ NOT NULL,
    reported_at     TIMESTAMPTZ,
    source_system   TEXT DEFAULT 'LIS',                 -- LIS / manual / import
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_lab_results_hn_collected
    ON lab_results (hn, collected_at DESC);

CREATE INDEX IF NOT EXISTS idx_lab_results_patient_collected
    ON lab_results (patient_id, collected_at DESC);

CREATE INDEX IF NOT EXISTS idx_lab_results_test_code
    ON lab_results (test_code);

-- =============================================================================
-- 5) Medical knowledge documents (RAG-ready)
-- =============================================================================
CREATE TABLE IF NOT EXISTS medical_knowledge_documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title           TEXT NOT NULL,
    slug            TEXT UNIQUE,
    category        TEXT NOT NULL DEFAULT 'general',      -- disease / drug / guideline / protocol
    source          TEXT,                                 -- ชื่อ guideline, textbook, URL
    source_url      TEXT,
    language        VARCHAR(10) NOT NULL DEFAULT 'th',
    content         TEXT NOT NULL,                        -- เนื้อหาเต็ม
    summary         TEXT,
    tags            TEXT[] DEFAULT '{}',
    version         TEXT,
    effective_from  DATE,
    effective_to    DATE,
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_med_knowledge_category
    ON medical_knowledge_documents (category)
    WHERE is_active = true;

CREATE INDEX IF NOT EXISTS idx_med_knowledge_tags
    ON medical_knowledge_documents USING gin (tags);

-- Full-text search (ไม่ต้องใช้ pgvector ก็ค้นหาได้)
CREATE INDEX IF NOT EXISTS idx_med_knowledge_fts
    ON medical_knowledge_documents
    USING gin (to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(content, '')));

-- แยก chunk สำหรับ embedding / retrieval (optional)
CREATE TABLE IF NOT EXISTS medical_knowledge_chunks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id     UUID NOT NULL REFERENCES medical_knowledge_documents (id) ON DELETE CASCADE,
    chunk_index     INT NOT NULL DEFAULT 0,
    content         TEXT NOT NULL,
    token_count     INT,
    -- embedding     vector(1536),                        -- เปิดเมื่อ enable pgvector
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_med_knowledge_chunks_doc
    ON medical_knowledge_chunks (document_id, chunk_index);

-- =============================================================================
-- updated_at triggers
-- =============================================================================
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_patients_updated_at ON patients;
CREATE TRIGGER trg_patients_updated_at
    BEFORE UPDATE ON patients
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_chat_sessions_updated_at ON chat_sessions;
CREATE TRIGGER trg_chat_sessions_updated_at
    BEFORE UPDATE ON chat_sessions
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_med_knowledge_updated_at ON medical_knowledge_documents;
CREATE TRIGGER trg_med_knowledge_updated_at
    BEFORE UPDATE ON medical_knowledge_documents
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- =============================================================================
-- Row Level Security (Supabase)
-- =============================================================================
ALTER TABLE chat_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE lab_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE medical_knowledge_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE medical_knowledge_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE patients ENABLE ROW LEVEL SECURITY;

-- Chat: user เห็นเฉพาะ session ของตัวเอง
CREATE POLICY chat_sessions_select_own ON chat_sessions
    FOR SELECT USING (auth.uid() = user_id);
CREATE POLICY chat_sessions_insert_own ON chat_sessions
    FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY chat_sessions_update_own ON chat_sessions
    FOR UPDATE USING (auth.uid() = user_id);
CREATE POLICY chat_sessions_delete_own ON chat_sessions
    FOR DELETE USING (auth.uid() = user_id);

CREATE POLICY chat_messages_select_own ON chat_messages
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM chat_sessions s
            WHERE s.id = chat_messages.session_id AND s.user_id = auth.uid()
        )
    );
CREATE POLICY chat_messages_insert_own ON chat_messages
    FOR INSERT WITH CHECK (
        EXISTS (
            SELECT 1 FROM chat_sessions s
            WHERE s.id = chat_messages.session_id AND s.user_id = auth.uid()
        )
    );

-- Lab + knowledge: authenticated users อ่านได้ (ปรับตาม policy โรงพยาบาล)
CREATE POLICY lab_results_select_auth ON lab_results
    FOR SELECT TO authenticated USING (true);

CREATE POLICY med_knowledge_select_auth ON medical_knowledge_documents
    FOR SELECT TO authenticated USING (is_active = true);

CREATE POLICY med_knowledge_chunks_select_auth ON medical_knowledge_chunks
    FOR SELECT TO authenticated USING (true);

CREATE POLICY patients_select_auth ON patients
    FOR SELECT TO authenticated USING (true);

-- =============================================================================
-- Sample seed data (optional — ลบได้ถ้าไม่ต้องการ)
-- =============================================================================
INSERT INTO patients (hn, full_name, sex)
VALUES ('123456', 'สมชาย ใจดี', 'M')
ON CONFLICT (hn) DO NOTHING;

INSERT INTO lab_results (hn, test_code, test_name, value_numeric, unit, ref_low, ref_high, flag, collected_at)
SELECT p.hn, v.test_code, v.test_name, v.value_numeric, v.unit, v.ref_low, v.ref_high, v.flag, v.collected_at
FROM patients p
CROSS JOIN (
    VALUES
        ('Hb',   'Hemoglobin', 12.5::numeric, 'g/dL', 12.0::numeric, 16.0::numeric, 'N', now() - interval '2 hours'),
        ('Cr',   'Creatinine',  1.1::numeric, 'mg/dL', 0.6::numeric,  1.2::numeric, 'N', now() - interval '2 hours'),
        ('eGFR', 'eGFR',       72.0::numeric, 'mL/min/1.73m2', 90.0::numeric, NULL::numeric, 'L', now() - interval '2 hours')
) AS v(test_code, test_name, value_numeric, unit, ref_low, ref_high, flag, collected_at)
WHERE p.hn = '123456'
ON CONFLICT DO NOTHING;

INSERT INTO medical_knowledge_documents (title, slug, category, source, content, tags)
VALUES (
    'สูตรคำนวณ BMI',
    'bmi-formula',
    'guideline',
    'WHO',
    'BMI = น้ำหนัก (kg) / ส่วนสูง (m)^2
ช่วงปกติ: 18.5–24.9 kg/m²
น้ำหนักเกิน: 25–29.9
อ้วน: ≥ 30',
    ARRAY['nutrition', 'bmi', 'general']
)
ON CONFLICT (slug) DO NOTHING;

INSERT INTO medical_knowledge_documents (title, slug, category, source, content, tags)
VALUES (
    'Vancomycin dosing — แนวทางเบื้องต้น',
    'vancomycin-dosing-basics',
    'drug',
    'Internal protocol (mock)',
    'ปรับ dose vancomycin ตาม renal function (CrCl/eGFR)
- ตรวจ Cr ล่าสุดก่อนคำนวณ
- พิจารณา loading dose และ maintenance ตาม protocol โรงพยาบาล
- ติดตาม trough level ตาม indication',
    ARRAY['vancomycin', 'antibiotic', 'renal']
)
ON CONFLICT (slug) DO NOTHING;
