-- =====================================================
-- 22. BỎ CHỨC NĂNG ĐẶT BÀN (TUỲ CHỌN)
-- App chỉ là app gọi món nên phần đặt bàn đã được gỡ khỏi code.
-- Bảng "reservations" vẫn còn trong database nhưng không còn được dùng.
-- Nếu muốn xoá hẳn (MẤT toàn bộ dữ liệu đặt bàn cũ, không khôi phục được) thì chạy file này.
-- Không chạy cũng không ảnh hưởng gì đến app.
-- =====================================================

DROP TABLE IF EXISTS reservations;
