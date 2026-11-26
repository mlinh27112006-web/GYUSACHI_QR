-- =====================================================
-- 21. THANH TOÁN NHIỀU HÌNH THỨC: bảng order_payments
-- Chạy SAU file 20. Chạy lại nhiều lần không sao (IF NOT EXISTS).
--
-- Mỗi lần thu tiền (tiền mặt / thẻ / chuyển khoản) là 1 dòng.
-- Tổng các dòng của một đơn phải bằng orders.total (app.py kiểm tra khi thanh toán).
-- Huỷ hoá đơn KHÔNG xoá các dòng này (giữ làm lịch sử); báo cáo loại bỏ đơn đã huỷ
-- bằng orders.voided_at.
-- =====================================================

CREATE TABLE IF NOT EXISTS order_payments (
    id         SERIAL PRIMARY KEY,
    order_id   INT         NOT NULL REFERENCES orders(id) ON DELETE RESTRICT,
    method     VARCHAR(20) NOT NULL CHECK (method IN ('CASH', 'CARD', 'TRANSFER')),
    amount     INT         NOT NULL CHECK (amount > 0),
    cashier_id VARCHAR(10) REFERENCES staffs(id),
    paid_at    TIMESTAMP   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_order_payments_order ON order_payments(order_id);

-- Chuyển dữ liệu cũ: mỗi hoá đơn đã thanh toán trước đây = 1 khoản thu đủ số tiền
INSERT INTO order_payments (order_id, method, amount, cashier_id, paid_at)
SELECT o.id, o.payment_method, o.total, o.cashier_id, o.paid_at
FROM orders o
WHERE o.paid_at IS NOT NULL
  AND o.payment_method IN ('CASH', 'CARD', 'TRANSFER')
  AND COALESCE(o.total, 0) > 0
  AND NOT EXISTS (SELECT 1 FROM order_payments p WHERE p.order_id = o.id);

-- Cột PIN phải đủ dài để lưu PIN đã băm (chạy hash_pins.py sau khi nạp file này).
ALTER TABLE staffs   ALTER COLUMN pin TYPE TEXT;
ALTER TABLE stations ALTER COLUMN pin TYPE TEXT;

-- Mỗi bàn chỉ có tối đa 1 đơn đang mở. Nếu đang có bàn trùng thì DỪNG và liệt kê bàn đó (không lặng lẽ bỏ qua).
DO $$
DECLARE dup TEXT;
BEGIN
    SELECT string_agg(table_id || ' (' || n || ' đơn)', ', ') INTO dup
    FROM (SELECT table_id, COUNT(*) AS n FROM orders WHERE status = 'OPEN' GROUP BY table_id HAVING COUNT(*) > 1) d;
    IF dup IS NOT NULL THEN
        RAISE EXCEPTION 'Các bàn đang có nhiều hơn 1 đơn OPEN: %. Thanh toán hoặc gộp bớt rồi chạy lại file này.', dup;
    END IF;
    CREATE UNIQUE INDEX IF NOT EXISTS uq_one_open_order_per_table ON orders(table_id) WHERE status = 'OPEN';
END $$;

-- Mỗi bàn chỉ có tối đa 1 yêu cầu gọi nhân viên đang mở cho mỗi loại. Có trùng thì DỪNG và liệt kê.
DO $$
DECLARE dup TEXT;
BEGIN
    SELECT string_agg(table_id || '/' || kind || ' (' || n || ')', ', ') INTO dup
    FROM (SELECT table_id, kind, COUNT(*) AS n FROM service_calls WHERE status = 'OPEN'
          GROUP BY table_id, kind HAVING COUNT(*) > 1) d;
    IF dup IS NOT NULL THEN
        RAISE EXCEPTION 'Có yêu cầu gọi nhân viên đang mở bị trùng: %. Đánh dấu xong bớt rồi chạy lại file này.', dup;
    END IF;
    CREATE UNIQUE INDEX IF NOT EXISTS uq_service_call_open ON service_calls(table_id, kind) WHERE status = 'OPEN';
END $$;

-- Kiểm tra cuối: PHẢI ra đúng 2 dòng (hai chỉ mục chống trùng). Ít hơn nghĩa là migration chưa hoàn tất.
SELECT indexname, tablename FROM pg_indexes
WHERE indexname IN ('uq_one_open_order_per_table', 'uq_service_call_open');

-- (Dùng khi cần) các bàn đang có nhiều hơn 1 đơn OPEN:
-- SELECT table_id, COUNT(*) FROM orders WHERE status = 'OPEN' GROUP BY table_id HAVING COUNT(*) > 1;
