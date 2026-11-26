# GYUSACHI – Web gọi món QR cho nhà hàng buffet

Ứng dụng Flask + PostgreSQL theo mô hình MVC. Khách quét QR ở bàn để gọi món; phục vụ, bếp, thu ngân và quản lí dùng các trang riêng.

## Nhóm thực hiện

| Người | Họ tên | MSSV | Tài khoản GitHub | Phần phụ trách |
|---|---|---|---|---|
| Nhóm trưởng | Tô Thị Mai Linh | 3120224088 | mlinh27112006-web | feature/mai-linh-core |
| Thành viên 2 | Trương Hồng Ngọc | 3120224101 | hongngoc060301-arch | feature/hong-ngoc-cashier |
| Thành viên 3 | Thái Nguyên An | 3120224001 | nguyenandn2006-bot | feature/nguyen-an-kitchen |
| Thành viên 4 | Nguyễn Thúy Hằng | 3120224046 | nguyenthuyhang240506-commits | feature/thuy-hang-staff |


## Cấu trúc

```
app.py, config.py      điểm vào, cấu hình (đọc .env)
core/                  db, helpers, auth (PIN, QR, phân quyền), audit (nhật ký), errors
models/                truy vấn CSDL và quy tắc tính toán
controllers/           9 Blueprint: auth, staff, customer, kitchen, cashier, report, menu, inventory, admin
views/                 giao diện (home, staff, customer, kitchen, cashier, manager)
SQL/                   23 file tạo CSDL (xem SQL/README.md)
tests/                 test_auth, test_billing, test_orders, test_inventory, test_structure
```

## Chạy thử

1. Cài Python 3.11 trở lên và PostgreSQL.
2. Sao chép `.env.example` thành `.env`, điền `DB_PASSWORD` và `SECRET_KEY`.
3. Tạo database rồi chạy các file trong `SQL/` theo thứ tự (xem `SQL/README.md`).
4. Chép thư mục `static/` (ảnh, logo) của web cũ vào thư mục gốc dự án.
5. `pip install -r requirements.txt`
6. `python app.py`, mở http://127.0.0.1:5000

Chạy kiểm thử: `pytest` (test_structure chỉ đạt khi đã gộp đủ phần của cả 4 người).

## Các trang

| Đường dẫn | Người dùng |
| --- | --- |
| `/` | Trang chủ, đăng nhập PIN nhân viên / trạm bếp |
| `/phucvu` | Phục vụ |
| `/bep` | Bếp |
| `/thungan` | Thu ngân |
| `/quanli` | Quản lí / Chủ / Admin |
| `/ban/<mã bàn>?k=...` | Khách quét QR |
| `/qr-ban` | In mã QR từng bàn (quản lí) |

Lưu ý: `views/staff/tang1.html` và `tang2.html` hiện chưa có route nào gọi tới (giữ lại làm sơ đồ tầng tham khảo).
