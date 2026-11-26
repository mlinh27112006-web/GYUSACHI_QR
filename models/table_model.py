"""Người phụ trách: Mai Linh
Mô tả: Truy vấn bàn ăn, thứ tự bàn tự nhiên và kiểm tra dữ liệu bàn.
"""

from core.db import query
from core.helpers import OrderError, clean_name


def get_tables(floor=None):
    sql = ("SELECT id, name, capacity, min_capacity, floor, type, status "
           "FROM dining_tables WHERE is_active")
    params = None
    if floor is not None:
        sql += " AND floor = %s"
        params = (floor,)
    # Xếp bàn thường theo số (B1..B11), phòng VIP đứng sau cùng
    sql += (" ORDER BY floor, (type = 'VIP'), "
            "NULLIF(regexp_replace(id, '\\D', '', 'g'), '')::int, id")
    return [dict(r) for r in query(sql, params)]


TABLE_FLOORS = (1, 2)


NATURAL_TABLE_ORDER = ("t.floor, (t.type = 'VIP'), "
                       "NULLIF(regexp_replace(t.id, '\\D', '', 'g'), '')::int, t.id")


def table_fields(data, partial=False):
    """Đọc + kiểm tra thông tin bàn. partial=True: chỉ kiểm tra các trường có gửi lên."""
    out = {}
    if 'name' in data or not partial:
        out['name'] = clean_name(data.get('name'), 50)
    if 'capacity' in data or not partial:
        try:
            out['capacity'] = int(data.get('capacity'))
        except (TypeError, ValueError):
            raise OrderError("Số chỗ không hợp lệ.")
        if not 1 <= out['capacity'] <= 30:
            raise OrderError("Số chỗ phải từ 1 đến 30.")
    if 'min_capacity' in data or not partial:
        try:
            out['min_capacity'] = int(data.get('min_capacity') or 1)
        except (TypeError, ValueError):
            raise OrderError("Số khách tối thiểu không hợp lệ.")
        if out['min_capacity'] < 1:
            raise OrderError("Số khách tối thiểu phải từ 1.")
    if 'floor' in data or not partial:
        try:
            out['floor'] = int(data.get('floor'))
        except (TypeError, ValueError):
            raise OrderError("Tầng không hợp lệ.")
        if out['floor'] not in TABLE_FLOORS:
            raise OrderError("Nhà hàng có tầng 1 và tầng 2.")
    if 'type' in data or not partial:
        out['type'] = str(data.get('type') or 'NORMAL').upper()
        if out['type'] not in ('NORMAL', 'VIP'):
            raise OrderError("Loại bàn không hợp lệ.")
    return out
