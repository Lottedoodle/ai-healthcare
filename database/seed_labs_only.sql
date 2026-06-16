-- รันบน Supabase SQL Editor (โปรเจกต์ gywexiihyzrocajnabna)
-- ถ้ารัน schema.sql แล้ว ข้ามได้

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
WHERE p.hn = '123456';

-- ให้ anon/publishable key อ่าน lab ได้ (backend ใช้ REST)
ALTER TABLE lab_results ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS lab_results_select_anon ON lab_results;
CREATE POLICY lab_results_select_anon ON lab_results
    FOR SELECT TO anon, authenticated USING (true);
