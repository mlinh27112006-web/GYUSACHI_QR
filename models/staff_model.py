"""Người phụ trách: Mai Linh
Mô tả: Truy vấn nhân viên và trạm bếp; kiểm tra PIN đã có người dùng chưa.
"""

from core.auth import pin_check
from core.db import query


def get_staffs():
    # KHÔNG lấy cột pin để không gửi PIN ra trình duyệt
    rows = query("SELECT id, name, role, avatar FROM staffs WHERE is_active AND role NOT IN ('Chủ', 'Admin') ORDER BY id")
    return [dict(r) for r in rows]


def get_stations():
    # description đổi tên thành "desc" để template (st.desc) dùng như cũ
    rows = query('SELECT id, name, icon, description AS "desc" FROM stations ORDER BY id')
    return [dict(r) for r in rows]


def pin_taken(cur, pin, except_staff=None, except_station=None):
    """PIN đã có người dùng chưa (so cả nhân viên lẫn trạm bếp). PIN lưu dạng băm nên phải so từng dòng."""
    cur.execute("SELECT pin FROM staffs WHERE id <> %s", (except_staff or '',))
    if any(pin_check(r['pin'], pin) for r in cur.fetchall()):
        return True
    cur.execute("SELECT pin FROM stations WHERE id <> %s", (except_station or '',))
    return any(pin_check(r['pin'], pin) for r in cur.fetchall())
