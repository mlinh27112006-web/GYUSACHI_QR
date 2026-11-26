"""Người phụ trách: Thúy Hằng
Mô tả: Đơn của bàn: chi tiết đơn, kiểm tra số khách, mở bàn (mỗi bàn tối đa một đơn mở).
"""

from core.db import query
from core.helpers import BUFFET_MINUTES, FOOD_PACKAGE_MIN_PRICE, OrderError, parse_days, vn_now


def order_detail(order_id):
    o = query("""
        SELECT o.id, o.table_id, o.staff_id, o.guests, o.status,
               to_char(o.created_at, 'HH24:MI') AS opened_at,
               o.package_id,       p.name AS package_name, p.price AS package_price,
               o.drink_package_id, d.name AS drink_name,   d.price AS drink_price
        FROM orders o
        LEFT JOIN packages p ON p.id = o.package_id
        LEFT JOIN packages d ON d.id = o.drink_package_id
        WHERE o.id = %s
    """, (order_id,), one=True)

    if not o:
        return None

    items = query("""
        SELECT id, parent_id, kind, name, station_id, qty, unit_price, status, note, source,
               to_char(created_at, 'HH24:MI') AS time
        FROM order_items WHERE order_id = %s ORDER BY id
    """, (order_id,))

    o = dict(o)
    o['items'] = [dict(i) for i in items]

    # Đồng hồ buffet: tính từ món đầu tiên của bàn (kể cả món sau đó bị huỷ, để không "reset" giờ bằng cách huỷ món)
    first = query("SELECT EXTRACT(EPOCH FROM (NOW() - MIN(created_at)))::int AS e "
                  "FROM order_items WHERE order_id = %s", (order_id,), one=True)
    has_buffet = bool(o['package_id'] or o['drink_package_id'])
    o['limit_min'] = BUFFET_MINUTES
    o['seconds_left'] = (BUFFET_MINUTES * 60 - first['e']) if (has_buffet and first and first['e'] is not None) else None
    return o


def parse_guests(value):
    """Đọc số khách (1..60) từ dữ liệu gửi lên. Raise OrderError nếu sai."""
    try:
        guests = int(value)
    except (TypeError, ValueError):
        raise OrderError("Số khách không hợp lệ.")
    if not 1 <= guests <= 60:
        raise OrderError("Số khách phải từ 1 đến 60.")
    return guests


def open_order_tx(cur, table_id, staff_id, guests, package_id, drink_id):
    """Mở bàn (tạo đơn OPEN + đánh dấu bàn đang dùng) bên trong 1 transaction có sẵn. Trả về id đơn.
    Raise OrderError nếu sai."""
    cur.execute("SELECT id FROM dining_tables WHERE id = %s AND is_active FOR UPDATE", (table_id,))
    if not cur.fetchone():
        raise OrderError("Không tìm thấy bàn.")

    cur.execute("SELECT id FROM orders WHERE table_id = %s AND status = 'OPEN'", (table_id,))
    if cur.fetchone():
        raise OrderError("Bàn này đang có khách, hãy tải lại trang.")

    cur.execute("SELECT id FROM staffs WHERE id = %s AND is_active", (staff_id,))
    if not cur.fetchone():
        raise OrderError("Không tìm thấy nhân viên.")

    if package_id:
        cur.execute("SELECT price FROM packages WHERE id = %s AND is_active", (package_id,))
        p = cur.fetchone()
        if not p or p['price'] < FOOD_PACKAGE_MIN_PRICE:
            raise OrderError("Gói buffet đồ ăn không hợp lệ.")

    if drink_id:
        cur.execute("SELECT price, valid_days FROM packages WHERE id = %s AND is_active", (drink_id,))
        p = cur.fetchone()
        if not p or p['price'] >= FOOD_PACKAGE_MIN_PRICE:
            raise OrderError("Gói buffet nước không hợp lệ.")
        days = parse_days(p['valid_days'])
        if days and vn_now().isoweekday() not in days:
            raise OrderError("Gói nước này không áp dụng hôm nay.")

    cur.execute("""
        INSERT INTO orders (table_id, staff_id, package_id, drink_package_id, guests)
        VALUES (%s, %s, %s, %s, %s) RETURNING id
    """, (table_id, staff_id, package_id, drink_id, guests))
    order_id = cur.fetchone()['id']

    cur.execute("UPDATE dining_tables SET status = 'OCCUPIED' WHERE id = %s", (table_id,))
    return order_id
