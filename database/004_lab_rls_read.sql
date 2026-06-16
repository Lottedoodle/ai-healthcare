-- ถ้า backend ยังอ่าน lab ไม่ได้: เปิดให้ anon อ่าน lab_results (dev/demo)
-- หรือใช้ JWT ของ user ที่ login (โค้ด backend ส่ง token แล้ว — policy authenticated ใช้ได้)

DROP POLICY IF EXISTS lab_results_select_anon ON lab_results;
CREATE POLICY lab_results_select_anon ON lab_results
    FOR SELECT TO anon, authenticated USING (true);

-- ตรวจข้อมูลใน table
-- SELECT hn, test_code, value_numeric, collected_at FROM lab_results ORDER BY collected_at DESC;
