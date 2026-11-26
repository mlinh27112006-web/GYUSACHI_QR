# Thứ tự chạy các file SQL

Tạo một database trống (ví dụ `Gyusachi-qr`) rồi chạy lần lượt từ 01 đến 23. Mỗi file dựa trên bảng/dữ liệu của file trước.

| File | Nội dung |
| --- | --- |
| 01_tao_bang | Tạo bảng cơ bản. **Xoá sạch bảng cũ** nếu đã có |
| 02_du_lieu_nen | Trạm bếp, bàn, nhân viên, gói buffet |
| 03_ham_nhap_mon | Hàm `add_to_package` để nhập món |
| 04 – 09 | Menu buffet 199K, 269K, 299K, 349K, 389K, 469K (gói sau gồm toàn bộ món gói trước) |
| 10_menu_alacarte | Món gọi lẻ. **TRUNCATE** `alacarte_items`, chạy lại phải chạy lại 11 và 14 |
| 11_menu_combo | Chi tiết combo (TRUNCATE `combo_details`) |
| 12_menu_buffet_nc | Buffet thức uống 49K / 69K / 139K |
| 13_thu_ngan | Cột lưu hoá đơn khi thanh toán |
| 14_quan_li | Cột bật/tắt món gọi lẻ (hết hàng) |
| 15_them_ban_B10_B11 | Thêm bàn B10, B11 |
| 16_menu_special | Menu Special cho gói 349K / 389K / 469K |
| 17_quan_li_nang_cao | Nhân viên, bàn, gói, cấu hình (`app_settings`) |
| 18_cau_hinh_nhat_ky | Huỷ hoá đơn và nhật ký thao tác |
| 19_kho_phuc_vu | Kho phục vụ. **Xoá và tạo lại** kho phục vụ mỗi lần chạy |
| 20_qr_goi_nhan_vien | QR gọi món tại bàn, gọi nhân viên / xin tính tiền |
| 21_thanh_toan_nhieu_lan | Bảng `order_payments` (nhiều hình thức thanh toán) |
| 22_bo_dat_ban | Tuỳ chọn: xoá bảng `reservations` (không khôi phục được) |
| 23_tai_khoan_chu_admin | Hai tài khoản Chủ và Admin |

Sau khi nạp xong, chạy một lần `python hash_pins.py` để băm các mã PIN.

**Cảnh báo:** file 01, 10, 11, 19 (và 22 nếu chạy) xoá dữ liệu. Chỉ dùng cho database mới hoặc thử nghiệm, không chạy trên dữ liệu thật. Có thể nạp tất cả một lần bằng `restore.py` (đọc `DATABASE_URL`, hỏi xác nhận trước khi xoá).
