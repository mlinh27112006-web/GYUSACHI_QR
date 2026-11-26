-- =====================================================
-- 23. HAI TÀI KHOẢN MỚI: CHỦ VÀ ADMIN
-- Chạy SAU file 21. Chạy lại nhiều lần không sao.
--
--   Chủ   : xem doanh thu, xuất Excel, huỷ/khôi phục hoá đơn, đổi giá gói, thuế & ưu đãi,
--           tài khoản ngân hàng, nhân viên và PIN, nhật ký.
--   Admin : bảo trì hệ thống (kiểm tra lỗi, dọn dữ liệu kẹt, đặt lại PIN, thêm/xoá bàn).
--   Quản lí (Anh Khoa): chỉ việc vận hành hằng ngày.
--
-- Hai tài khoản này KHÔNG xuất hiện ở danh sách phục vụ / thu ngân.
-- PIN mặc định bên dưới chỉ để thử: ĐỔI NGAY sau khi đăng nhập lần đầu
-- (Chủ đổi ở mục Nhân viên; Admin nhờ Chủ hoặc đổi trong database).
-- Sau khi chạy file này, chạy lại:  python hash_pins.py
-- =====================================================

INSERT INTO staffs (id, name, role, pin, avatar) VALUES
    ('CHU', 'Chủ nhà hàng',     'Chủ',   '1357', NULL),
    ('ADM', 'Quản trị hệ thống', 'Admin', '2468', NULL)
ON CONFLICT (id) DO NOTHING;

SELECT id, name, role FROM staffs WHERE role IN ('Chủ', 'Admin');
