"""Người phụ trách: Mai Linh
Mô tả: Nạp database từ thư mục SQL/.

Nạp database từ thư mục SQL/ (hoặc file gyusachi_backup.sql).

CẢNH BÁO: file SQL 01 và 19 XOÁ SẠCH các bảng rồi tạo lại. Chỉ dùng cho database mới/thử nghiệm,
KHÔNG chạy trên database đang có dữ liệu thật.

Cách dùng (địa chỉ database đọc từ biến môi trường, không ghi trong mã nguồn):
    PowerShell:  $env:DATABASE_URL = 'postgresql://user:matkhau@host:5432/tendb'
                 python restore.py --yes-reset-database
"""
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import psycopg2

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    sys.exit("Thiếu biến môi trường DATABASE_URL. Xem hướng dẫn ở đầu file restore.py.")
if "--yes-reset-database" not in sys.argv:
    sys.exit("Script này XOÁ SẠCH dữ liệu hiện có. Nếu chắc chắn, chạy lại với cờ --yes-reset-database")

target = urlparse(DATABASE_URL)
db_name = target.path.lstrip("/")
print(f"Máy chủ: {target.hostname}  |  Database: {db_name}")
if input(f"Gõ đúng tên database '{db_name}' để xác nhận XOÁ và nạp lại: ").strip() != db_name:
    sys.exit("Tên không khớp, đã huỷ.")

backup_file = Path("gyusachi_backup.sql")
sql_dir = Path("SQL")

if backup_file.exists():
    scripts = [backup_file]
elif sql_dir.exists():
    scripts = sorted(sql_dir.glob("*.sql"))
else:
    scripts = []
if not scripts:
    sys.exit("LỖI: không tìm thấy gyusachi_backup.sql lẫn thư mục SQL/ có file .sql. Chưa thay đổi gì.")

print("Sẽ chạy theo thứ tự:")
for f in scripts:
    print("  -", f.name)
if len(scripts) < 5 and not backup_file.exists():
    print("CẢNH BÁO: thư mục SQL/ có rất ít file, có thể thiếu các file schema 01-20.")
if input("Gõ YES để bắt đầu: ").strip() != "YES":
    sys.exit("Đã huỷ.")

# Tất cả file chạy trong MỘT giao dịch: file nào lỗi thì huỷ toàn bộ, không để dở dang.
conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = False
cur = conn.cursor()
try:
    for file_path in scripts:
        print(f" -> Đang chạy: {file_path.name}")
        with open(file_path, "r", encoding="utf-8") as f:
            cur.execute(f.read())
    conn.commit()
except Exception as e:
    conn.rollback()
    sys.exit(f"\nLỖI ở file {file_path.name}: {e}\nĐã HUỶ toàn bộ, database giữ nguyên như cũ.")
finally:
    cur.close()
    conn.close()
print("\n===> NẠP DỮ LIỆU XONG! <===")
