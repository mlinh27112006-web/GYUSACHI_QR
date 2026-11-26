"""Người phụ trách: Thúy Hằng
Mô tả: Phục vụ: sơ đồ bàn, mở bàn, chuyển/gộp bàn, đổi gói, gọi món, huỷ món, yêu cầu gọi nhân viên.
"""

from flask import render_template, request, jsonify, redirect, url_for, session, Blueprint

from core.auth import manager_ok, qr_ok
from core.db import query, transaction
from core.helpers import (
    BUFFET_MINUTES,
    BUFFET_WARN_MINUTES,
    DESSERT_CATEGORY,
    FOOD_PACKAGE_MIN_PRICE,
    OrderError,
    fail,
    group_by_category,
    parse_days,
    vn_now,
)
from models.order_model import open_order_tx, order_detail, parse_guests
from models.table_model import get_tables

bp = Blueprint('staff', __name__)


@bp.route('/phucvu')
def phucvu():
    staff_id = request.args.get('staff')

    staff = query(
        "SELECT id, name, role, avatar FROM staffs WHERE id = %s",
        (staff_id,), one=True
    )

    if not staff or session.get('staff') != staff['id']:
        return redirect(url_for('auth.home'))             # chưa nhập PIN (hoặc đổi sang ID khác) -> về trang đăng nhập

    return render_template(
        'staff/phucvu.html',
        staff=dict(staff),
        tables=get_tables()
    )


@bp.route('/api/tables')
def api_tables():
    """Danh sách bàn + trạng thái hiện tại (để tô màu bàn đang dùng)."""
    rows = query("""
        SELECT t.id, t.name, t.capacity, t.min_capacity, t.floor, t.type, t.status,
               o.id AS order_id, o.guests, o.package_id, o.drink_package_id,
               (o.package_id IS NOT NULL OR o.drink_package_id IS NOT NULL) AS has_buffet,
               (SELECT EXTRACT(EPOCH FROM (NOW() - MIN(oi.created_at)))::int
                  FROM order_items oi WHERE oi.order_id = o.id) AS elapsed_sec
        FROM dining_tables t
        LEFT JOIN orders o ON o.table_id = t.id AND o.status = 'OPEN'
        WHERE t.is_active
        ORDER BY t.floor, (t.type = 'VIP'),
                 NULLIF(regexp_replace(t.id, '\\D', '', 'g'), '')::int, t.id
    """)
    return jsonify({"tables": [dict(r) for r in rows],
                    "limit_sec": BUFFET_MINUTES * 60, "warn_sec": BUFFET_WARN_MINUTES * 60})


@bp.route('/api/packages')
def api_packages():
    """Các gói buffet. today_ok = gói có áp dụng hôm nay không (49K: T2-T5, 69K: T6-CN)."""
    today = vn_now().isoweekday()          # 1 = thứ 2 ... 7 = chủ nhật
    food, drink = [], []

    for r in query("SELECT id, name, price, valid_days FROM packages WHERE is_active ORDER BY price"):
        days = parse_days(r['valid_days'])
        item = {
            "id": r['id'], "name": r['name'], "price": r['price'],
            "today_ok": (not days) or (today in days),
        }
        (food if r['price'] >= FOOD_PACKAGE_MIN_PRICE else drink).append(item)

    return jsonify({"food": food, "drink": drink, "today": today})


@bp.route('/api/menu/package/<int:package_id>')
def api_menu_package(package_id):
    """Món có trong 1 gói buffet, chia theo nhóm."""
    rows = query("""
        SELECT m.id, m.name, m.category
        FROM package_items pi
        JOIN menu_items m ON m.id = pi.menu_item_id
        WHERE pi.package_id = %s AND m.is_active
        ORDER BY m.id
    """, (package_id,))
    return jsonify({"categories": group_by_category([dict(r) for r in rows])})


@bp.route('/api/menu/alacarte')
def api_menu_alacarte():
    """Món gọi lẻ (có giá), gồm cả thức uống, set thịt và combo."""
    rows = [dict(r) for r in query("""
        SELECT id, name, category, price::int AS price
        FROM alacarte_items WHERE is_active {drink_only} ORDER BY id
    """.format(drink_only="AND station_code = 'ST01'" if request.args.get('drinks') else ''))]

    parts_by_combo = {}
    for p in query("""
        SELECT id, combo_id, item_name AS name, quantity AS qty, choices
        FROM combo_details ORDER BY id
    """):
        parts_by_combo.setdefault(p['combo_id'], []).append({
            "id": p['id'], "name": p['name'], "qty": p['qty'],
            "choices": p['choices'].split('|') if p['choices'] else None,
        })

    for r in rows:
        r['parts'] = parts_by_combo.get(r['id'])      # None nếu không phải combo/set
        r['is_combo'] = r['parts'] is not None

    return jsonify({"categories": group_by_category(rows)})


@bp.route('/api/orders/<int:order_id>')
def api_order(order_id):
    if not (session.get('staff') or manager_ok() or session.get('cashier')):
        return fail("Hết phiên đăng nhập, hãy đăng nhập lại.", 401)
    o = order_detail(order_id)
    if not o:
        return fail("Không tìm thấy đơn.", 404)
    return jsonify({"success": True, "order": o})


@bp.route('/api/orders/open', methods=['POST'])
def api_open_order():
    """Mở bàn: tạo đơn mới cho bàn."""
    data = request.get_json() or {}
    try:
        guests = parse_guests(data.get('guests', 1))
        with transaction() as cur:
            order_id = open_order_tx(cur, data.get('table_id'), data.get('staff_id'), guests,
                                     data.get('package_id') or None, data.get('drink_package_id') or None)
    except OrderError as e:
        return fail(str(e))
    except Exception as e:
        if getattr(e, 'pgcode', None) == '23505':       # vi phạm duy nhất: bàn vừa được người khác mở
            return fail("Bàn này vừa được mở bởi người khác, hãy tải lại.", 409)
        raise

    return jsonify({"success": True, "order": order_detail(order_id)})


@bp.route('/api/orders/<int:order_id>/move', methods=['POST'])
def api_move_order(order_id):
    """Chuyển bàn: đưa nguyên đơn đang mở sang một bàn TRỐNG khác (món, vé, đồng hồ 120 phút đều giữ nguyên).
    Trả về cảnh báo (không chặn) nếu bàn mới thiếu chỗ hoặc sắp có khách đặt."""
    to_id = str((request.get_json() or {}).get('to_table_id') or '')
    warnings = []
    try:
        with transaction() as cur:
            cur.execute("SELECT id, table_id, status, guests FROM orders WHERE id = %s FOR UPDATE", (order_id,))
            o = cur.fetchone()
            if not o:
                raise OrderError("Không tìm thấy đơn.")
            if o['status'] != 'OPEN':
                raise OrderError("Đơn này đã kết thúc.")
            if o['table_id'] == to_id:
                raise OrderError("Hãy chọn một bàn khác với bàn hiện tại.")

            cur.execute("""SELECT id, name, capacity, min_capacity, type FROM dining_tables
                           WHERE id = %s AND is_active FOR UPDATE""", (to_id,))
            t = cur.fetchone()
            if not t:
                raise OrderError("Không tìm thấy bàn muốn chuyển tới.")
            cur.execute("SELECT 1 FROM orders WHERE table_id = %s AND status = 'OPEN'", (to_id,))
            if cur.fetchone():
                raise OrderError(f"Bàn {t['name'] or t['id']} đang có khách. Muốn nhập chung hai bàn hãy dùng 'Gộp bàn'.")

            cur.execute("UPDATE orders SET table_id = %s WHERE id = %s", (to_id, order_id))
            cur.execute("UPDATE dining_tables SET status = 'AVAILABLE' WHERE id = %s", (o['table_id'],))
            cur.execute("UPDATE dining_tables SET status = 'OCCUPIED' WHERE id = %s", (to_id,))
            cur.execute("UPDATE service_calls SET table_id = %s WHERE order_id = %s AND status = 'OPEN'",
                        (to_id, order_id))

            guests = o['guests'] or 0
            if t['type'] == 'VIP' and guests < (t['min_capacity'] or 1):
                warnings.append(f"Phòng VIP {t['id']} nhận từ {t['min_capacity']} khách (bàn đang có {guests}).")
            elif guests > t['capacity']:
                warnings.append(f"Bàn {t['id']} chỉ có {t['capacity']} chỗ (bàn đang có {guests} khách).")
    except OrderError as e:
        return fail(str(e))
    except Exception as e:
        if getattr(e, 'pgcode', None) == '23505':       # bàn vừa được người khác dùng
            return fail("Bàn đích vừa được người khác sử dụng, hãy tải lại danh sách bàn.", 409)
        raise

    return jsonify({"success": True, "order": order_detail(order_id), "warnings": warnings})


@bp.route('/api/orders/<int:order_id>/merge', methods=['POST'])
def api_merge_orders(order_id):
    """Gộp bàn: chuyển toàn bộ món + số khách của bàn khác (from_table_id) vào đơn này; bàn kia trở về trống.
    Chỉ gộp được khi hai bàn dùng cùng vé buffet (vì hoá đơn tính 1 vé × số khách)."""
    from_table = str((request.get_json() or {}).get('from_table_id') or '')
    try:
        with transaction() as cur:
            cur.execute("SELECT id FROM orders WHERE table_id = %s AND status = 'OPEN'", (from_table,))
            src = cur.fetchone()
            if not src:
                raise OrderError("Bàn cần gộp hiện không có khách.")
            if src['id'] == order_id:
                raise OrderError("Không thể gộp một bàn vào chính nó.")

            # khoá theo thứ tự id để 2 người gộp cùng lúc không bị kẹt nhau
            cur.execute("""SELECT id, table_id, status, guests, package_id, drink_package_id FROM orders
                           WHERE id = ANY(%s) ORDER BY id FOR UPDATE""", ([order_id, src['id']],))
            rows = {r['id']: r for r in cur.fetchall()}
            main, other = rows.get(order_id), rows.get(src['id'])
            if not main or not other or main['status'] != 'OPEN' or other['status'] != 'OPEN' \
                    or other['table_id'] != from_table:
                raise OrderError("Một trong hai bàn vừa thay đổi, hãy tải lại trang rồi thử lại.")

            if main['package_id'] != other['package_id'] or main['drink_package_id'] != other['drink_package_id']:
                raise OrderError("Hai bàn đang dùng vé buffet khác nhau. Hãy dùng 'Đổi vé' cho giống nhau rồi gộp lại.")

            total = (main['guests'] or 0) + (other['guests'] or 0)
            if total > 60:
                raise OrderError("Tổng số khách sau khi gộp vượt quá 60.")

            cur.execute("UPDATE order_items SET order_id = %s WHERE order_id = %s", (order_id, other['id']))
            cur.execute("UPDATE orders SET guests = %s WHERE id = %s", (total, order_id))

            # yêu cầu đang chờ của bàn kia: trùng loại với bàn này thì coi như đã xử lý, còn lại chuyển sang bàn này
            cur.execute("""UPDATE service_calls c SET status = 'DONE', done_at = NOW(), done_by = 'Gộp bàn'
                           WHERE c.order_id = %s AND c.status = 'OPEN'
                             AND EXISTS (SELECT 1 FROM service_calls m
                                         WHERE m.table_id = %s AND m.kind = c.kind AND m.status = 'OPEN')""",
                        (other['id'], main['table_id']))
            cur.execute("UPDATE service_calls SET table_id = %s, order_id = %s WHERE order_id = %s AND status = 'OPEN'",
                        (main['table_id'], order_id, other['id']))

            cur.execute("DELETE FROM orders WHERE id = %s", (other['id'],))        # đã chuyển hết món nên đơn rỗng
            cur.execute("UPDATE dining_tables SET status = 'AVAILABLE' WHERE id = %s", (from_table,))
    except OrderError as e:
        return fail(str(e))
    except Exception as e:
        if getattr(e, 'pgcode', None) == '23505':       # bàn vừa được người khác dùng
            return fail("Bàn đích vừa được người khác sử dụng, hãy tải lại danh sách bàn.", 409)
        raise

    return jsonify({"success": True, "order": order_detail(order_id)})


@bp.route('/api/orders/<int:order_id>/change-package', methods=['POST'])
def api_change_package(order_id):
    """Đổi vé buffet (đồ ăn và/hoặc nước) khi bàn đang gọi món.
    Món đã gọi giữ nguyên; nếu có món (chưa huỷ) không nằm trong gói mới thì không cho đổi."""
    data = request.get_json() or {}
    package_id = data.get('package_id') or None
    drink_id = data.get('drink_package_id') or None

    try:
        with transaction() as cur:
            cur.execute("SELECT id, status, package_id, drink_package_id FROM orders WHERE id = %s FOR UPDATE",
                        (order_id,))
            order = cur.fetchone()
            if not order:
                raise OrderError("Không tìm thấy đơn.")
            if order['status'] != 'OPEN':
                raise OrderError("Đơn này đã kết thúc.")
            if package_id == order['package_id'] and drink_id == order['drink_package_id']:
                raise OrderError("Bạn chưa chọn vé khác với vé hiện tại.")

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
                if drink_id != order['drink_package_id']:
                    days = parse_days(p['valid_days'])
                    if days and vn_now().isoweekday() not in days:
                        raise OrderError("Gói nước này không áp dụng hôm nay.")

            # món buffet đã gọi mà gói mới không có -> chặn
            new_pkgs = [x for x in (package_id, drink_id) if x]
            cur.execute("""
                SELECT DISTINCT oi.name
                FROM order_items oi
                WHERE oi.order_id = %s AND oi.kind = 'PACKAGE' AND oi.status <> 'CANCELLED'
                  AND NOT EXISTS (
                      SELECT 1 FROM package_items pi
                      WHERE pi.menu_item_id = oi.menu_item_id AND pi.package_id = ANY(%s))
                ORDER BY oi.name
            """, (order_id, new_pkgs))
            bad = [r['name'] for r in cur.fetchall()]
            if bad:
                shown = ', '.join(bad[:5]) + ('...' if len(bad) > 5 else '')
                raise OrderError(f"Bàn đã gọi {len(bad)} món không có trong vé mới ({shown}). "
                                 "Huỷ các món đó (nếu bếp chưa làm) rồi đổi lại.")

            cur.execute("UPDATE orders SET package_id = %s, drink_package_id = %s WHERE id = %s",
                        (package_id, drink_id, order_id))

    except OrderError as e:
        return fail(str(e))

    return jsonify({"success": True, "order": order_detail(order_id)})


def is_customer_request(data):
    """Người gọi là KHÁCH quét QR? Do SERVER quyết định, không tin cờ do trình duyệt gửi:
    chỉ nhân viên đã nhập PIN (có session) mới được gọi như nhân viên. Khách giả mạo không gửi cờ 'QR' vẫn bị coi là khách."""
    if data.get('source') == 'QR':
        return True
    return not (session.get('staff') or manager_ok())


@bp.route('/api/orders/<int:order_id>/items', methods=['POST'])
def api_add_items(order_id):
    """Gửi món xuống bếp. Mỗi món: {type:'PACKAGE'|'ALACARTE', id, qty, choices:{partId: 'tên'}}"""
    data = request.get_json() or {}
    items = data.get('items') or []
    customer = is_customer_request(data)

    if not items:
        return fail("Chưa chọn món nào.")
    if customer:
        # Khách tự gọi: chỉ món trong buffet và nước lẻ (quầy bar ST01); món lẻ khác gọi nhân viên
        for it in items:
            if it.get('type') == 'PACKAGE':
                continue
            ok = it.get('type') == 'ALACARTE' and query(
                "SELECT 1 FROM alacarte_items WHERE id = %s AND station_code = 'ST01' AND is_active",
                (it.get('id'),), one=True)
            if not ok:
                return fail("Món này vui lòng bấm 'Gọi nhân viên' để được phục vụ.")

    try:
        with transaction() as cur:
            cur.execute("""SELECT id, table_id, package_id, drink_package_id, status
                           FROM orders WHERE id = %s FOR UPDATE""", (order_id,))
            order = cur.fetchone()
            if not order:
                raise OrderError("Không tìm thấy đơn.")
            if customer and not qr_ok(order['table_id'], request.headers.get('X-Table-Key')):
                raise OrderError("Mã QR không hợp lệ cho bàn này, hãy quét lại mã trên bàn.")
            if order['status'] != 'OPEN':
                raise OrderError("Đơn này đã kết thúc.")

            package_ids = [p for p in (order['package_id'], order['drink_package_id']) if p]
            cur.execute("SELECT COALESCE(MAX(id), 0) AS m FROM order_items")
            first_new = cur.fetchone()['m']

            # Khách tự gọi qua QR mà đã quá giờ buffet: chỉ còn gọi được tráng miệng (nhân viên vẫn gọi được bình thường)
            if customer and package_ids:
                cur.execute("""SELECT EXTRACT(EPOCH FROM (NOW() - MIN(created_at)))::int AS e
                               FROM order_items WHERE order_id = %s""", (order_id,))
                e = cur.fetchone()['e']
                if e is not None and e >= BUFFET_MINUTES * 60:
                    msg = (f"Đã hết {BUFFET_MINUTES} phút gọi món. Quý khách chỉ còn gọi thêm được tráng miệng, "
                           "hoặc bấm 'Gọi nhân viên' / 'Xin tính tiền'.")
                    if not all(it.get('type') == 'PACKAGE' for it in items):
                        raise OrderError(msg)
                    try:
                        ids = {int(it.get('id')) for it in items}
                    except (TypeError, ValueError):
                        raise OrderError(msg)
                    cur.execute("SELECT COUNT(*) AS n FROM menu_items WHERE id = ANY(%s) AND category = %s",
                                (list(ids), DESSERT_CATEGORY))
                    if cur.fetchone()['n'] != len(ids):
                        raise OrderError(msg)

            for it in items:
                try:
                    qty = int(it.get('qty', 1))
                except (TypeError, ValueError):
                    raise OrderError("Số lượng không hợp lệ.")
                if not 1 <= qty <= 99:
                    raise OrderError("Số lượng mỗi món phải từ 1 đến 99.")

                kind = it.get('type')
                item_id = it.get('id')
                note = (it.get('note') or '').strip()[:200] or None

                # ---- món trong buffet ----
                if kind == 'PACKAGE':
                    if not package_ids:
                        raise OrderError("Bàn này chưa chọn gói buffet.")
                    cur.execute("""
                        SELECT m.id, m.name, m.station_id
                        FROM menu_items m
                        JOIN package_items pi ON pi.menu_item_id = m.id
                        WHERE m.id = %s AND m.is_active AND pi.package_id = ANY(%s)
                    """, (item_id, package_ids))
                    m = cur.fetchone()
                    if not m:
                        raise OrderError("Món không nằm trong gói buffet của bàn.")
                    cur.execute("""
                        INSERT INTO order_items (order_id, kind, menu_item_id, name, station_id, qty, unit_price, note)
                        VALUES (%s, 'PACKAGE', %s, %s, %s, %s, 0, %s)
                    """, (order_id, m['id'], m['name'], m['station_id'], qty, note))

                # ---- món gọi lẻ / combo ----
                elif kind == 'ALACARTE':
                    cur.execute("""SELECT id, name, station_code, price::int AS price, is_active
                                   FROM alacarte_items WHERE id = %s""", (item_id,))
                    a = cur.fetchone()
                    if not a:
                        raise OrderError("Không tìm thấy món gọi lẻ.")
                    if not a['is_active']:
                        raise OrderError(f"Món \"{a['name']}\" tạm hết, hãy bỏ khỏi giỏ.")

                    cur.execute("""SELECT id, item_name, station_code, quantity, choices
                                   FROM combo_details WHERE combo_id = %s ORDER BY id""", (a['id'],))
                    parts = cur.fetchall()

                    # khách QR chỉ được gọi combo mà mọi món con đều thuộc quầy bar (ST01)
                    if customer and (a['station_code'] != 'ST01' or any(p_['station_code'] != 'ST01' for p_ in parts)):
                        raise OrderError("Món này vui lòng bấm 'Gọi nhân viên' để được phục vụ.")

                    if not parts:
                        cur.execute("""
                            INSERT INTO order_items (order_id, kind, name, station_id, qty, unit_price, note)
                            VALUES (%s, 'ALACARTE', %s, %s, %s, %s, %s)
                        """, (order_id, a['name'], a['station_code'], qty, a['price'], note))
                        continue

                    # combo: 1 dòng tổng (tính tiền) + các dòng con (gửi bếp)
                    cur.execute("""
                        INSERT INTO order_items (order_id, kind, name, station_id, qty, unit_price, note)
                        VALUES (%s, 'COMBO', %s, NULL, %s, %s, %s) RETURNING id
                    """, (order_id, a['name'], qty, a['price'], note))
                    parent_id = cur.fetchone()['id']

                    chosen = it.get('choices') or {}
                    for p in parts:
                        name = p['item_name']
                        if p['choices']:
                            options = p['choices'].split('|')
                            pick = chosen.get(str(p['id']))
                            if pick not in options:
                                raise OrderError(f"Hãy chọn món cho: {p['item_name']}")
                            name = pick
                        cur.execute("""
                            INSERT INTO order_items (order_id, parent_id, kind, name, station_id, qty, unit_price, note)
                            VALUES (%s, %s, 'COMBO_PART', %s, %s, %s, 0, %s)
                        """, (order_id, parent_id, name, p['station_code'], p['quantity'] * qty, note))   # món con gửi bếp nên cũng mang ghi chú

                else:
                    raise OrderError("Loại món không hợp lệ.")

            if customer:                                 # khách tự gọi qua mã QR ở bàn
                cur.execute("UPDATE order_items SET source = 'QR' WHERE order_id = %s AND id > %s", (order_id, first_new))

    except OrderError as e:
        return fail(str(e))

    return jsonify({"success": True, "order": order_detail(order_id)})


@bp.route('/api/order-items/<int:item_id>/cancel', methods=['POST'])
def api_cancel_item(item_id):
    """Huỷ món — chỉ huỷ được khi bếp CHƯA nhận làm (trạng thái NEW), đơn đang mở, và người huỷ có quyền:
    nhân viên đã nhập PIN (phục vụ/quản lí) hoặc khách ở đúng bàn (gửi kèm table_id của bàn quét QR)."""
    data = request.get_json() or {}
    try:
        with transaction() as cur:
            cur.execute("SELECT order_id FROM order_items WHERE id = %s", (item_id,))
            first = cur.fetchone()
            if not first:
                raise OrderError("Không tìm thấy món.")
            cur.execute("SELECT table_id, status FROM orders WHERE id = %s FOR UPDATE", (first['order_id'],))
            od = cur.fetchone()
            cur.execute("SELECT id, order_id, kind, status FROM order_items WHERE id = %s FOR UPDATE",
                        (item_id,))
            it = cur.fetchone()
            if not it:
                raise OrderError("Không tìm thấy món.")
            if not od or od['status'] != 'OPEN':
                raise OrderError("Đơn này đã đóng, không huỷ món được nữa.")
            if is_customer_request(data):
                if not qr_ok(od['table_id'], request.headers.get('X-Table-Key')):
                    raise OrderError("Mã QR không hợp lệ cho bàn này, hãy quét lại mã trên bàn.")
            if it['kind'] == 'COMBO_PART':
                raise OrderError("Hãy huỷ cả combo, không huỷ riêng từng món trong combo.")

            if it['kind'] == 'COMBO':
                cur.execute("SELECT COUNT(*) AS n FROM order_items WHERE parent_id = %s AND status <> 'NEW'",
                            (item_id,))
                if cur.fetchone()['n'] > 0:
                    raise OrderError("Bếp đã làm một phần combo, không huỷ được nữa.")
                cur.execute("""UPDATE order_items SET status = 'CANCELLED', updated_at = NOW()
                               WHERE id = %s OR parent_id = %s""", (item_id, item_id))
            else:
                if it['status'] != 'NEW':
                    raise OrderError("Bếp đã nhận làm món này, không huỷ được nữa.")
                cur.execute("UPDATE order_items SET status = 'CANCELLED', updated_at = NOW() WHERE id = %s",
                            (item_id,))
            order_id = it['order_id']
    except OrderError as e:
        return fail(str(e))

    return jsonify({"success": True, "order": order_detail(order_id)})


@bp.route('/api/service-calls')
def api_service_calls():
    """Danh sách yêu cầu đang chờ (màn hình phục vụ). ?staff=ID để đánh dấu bàn do mình phụ trách."""
    me = session.get('staff') or ''               # lấy từ phiên đăng nhập, không tin tham số trình duyệt gửi
    rows = query("""
        SELECT c.id, c.table_id, c.kind, to_char(c.created_at, 'HH24:MI') AS at,
               EXTRACT(EPOCH FROM (NOW() - c.created_at))::int AS waiting,
               o.staff_id, s.name AS staff_name
        FROM service_calls c
        LEFT JOIN orders o ON o.id = c.order_id
        LEFT JOIN staffs s ON s.id = o.staff_id
        WHERE c.status = 'OPEN' ORDER BY c.id""")
    calls = [{**dict(r), "mine": bool(me) and r['staff_id'] == me} for r in rows]
    return jsonify({"calls": calls})


@bp.route('/api/service-calls/<int:call_id>/done', methods=['POST'])
def api_service_call_done(call_id):
    who = query("SELECT name FROM staffs WHERE id = %s",
                (session.get('staff') or session.get('manager_id'),), one=True)   # người xử lý = người đang đăng nhập
    with transaction() as cur:
        cur.execute("""UPDATE service_calls SET status = 'DONE', done_at = NOW(), done_by = %s
                       WHERE id = %s AND status = 'OPEN' RETURNING id""", (who['name'] if who else None, call_id))
        if not cur.fetchone():
            return fail("Yêu cầu này đã được xử lý.", 409)
    return jsonify({"success": True})
