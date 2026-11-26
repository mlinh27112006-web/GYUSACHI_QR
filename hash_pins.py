"""Người phụ trách: Mai Linh
Mô tả: Băm các PIN cũ còn lưu dạng chữ (chạy một lần).

Chuyển toàn bộ PIN đang lưu dạng chữ (nhân viên + trạm bếp) sang dạng băm.

Chạy MỘT LẦN sau khi nạp SQL/21_thanh_toan_nhieu_lan.sql (nó đã đổi cột PIN sang TEXT):
    python hash_pins.py

An toàn khi chạy lại: PIN đã băm sẽ được bỏ qua. PIN dùng để đăng nhập vẫn giữ nguyên (1111, 2222...).
Dùng cùng cấu hình database với app (biến môi trường DB_PASSWORD / DATABASE_URL như config.py).
"""
from werkzeug.security import generate_password_hash

from core.db import transaction

PREFIXES = ('pbkdf2:', 'scrypt:')

done = 0
with transaction() as cur:
    cur.execute("ALTER TABLE staffs   ALTER COLUMN pin TYPE TEXT")
    cur.execute("ALTER TABLE stations ALTER COLUMN pin TYPE TEXT")
    for table in ('staffs', 'stations'):
        cur.execute(f"SELECT id, pin FROM {table}")
        for row in cur.fetchall():
            pin = row['pin'] or ''
            if pin and not pin.startswith(PREFIXES):
                cur.execute(f"UPDATE {table} SET pin = %s WHERE id = %s",
                            (generate_password_hash(pin, method='pbkdf2:sha256:100000'), row['id']))
                done += 1
print(f"Đã băm {done} mã PIN.")
