"""Người phụ trách: Mai Linh
Mô tả: Quản trị: trang Quản lí, nhân viên, bàn, gói buffet, cấu hình, nhật ký, hệ thống, QR bàn, tài khoản nhận chuyển khoản.
"""

import os
import re

from flask import render_template, request, jsonify, redirect, session, current_app, Blueprint

from core.audit import audit
from core.auth import HIDDEN_ROLES, check_pin, current_mgr, manager_ok, mgr_role, pin_hash, qr_token
from core.db import query, transaction
from core.helpers import FOOD_PACKAGE_MIN_PRICE, OrderError, clean_name, fail, lan_ip, parse_days, vn_now
from models.settings_model import (
    SETTING_KEYS,
    _SETTINGS_CACHE,
    days_label,
    default_settings,
    get_settings,
    parse_holiday,
    payment_config,
)
from models.staff_model import pin_taken
from models.table_model import NATURAL_TABLE_ORDER, table_fields

bp = Blueprint('admin', __name__)


@bp.route('/quanli')
def quanli():
    return render_template('manager/quanli.html')


@bp.route('/api/manager/settings')
def api_manager_settings_get():
    return jsonify({"settings": get_settings(force=True), "defaults": default_settings()})


@bp.route('/api/manager/settings', methods=['POST'])
def api_manager_settings_save():
    data = request.get_json() or {}
    try:
        if data.get('reset'):
            new = default_settings()
        else:
            try:
                vat = round(float(data.get('vat_percent')), 2)
                lunch = int(data.get('lunch_end_hour'))
                group = int(data.get('group_size'))
                days = sorted({int(x) for x in (data.get('dinner_days') or [])})
            except (TypeError, ValueError):
                raise OrderError("Giá trị cấu hình không hợp lệ.")
            if not 0 <= vat <= 30:
                raise OrderError("VAT phải từ 0 đến 30%.")
            if not 10 <= lunch <= 20:
                raise OrderError("Giờ kết thúc buổi trưa phải từ 10 đến 20 giờ.")
            if not 2 <= group <= 20:
                raise OrderError("Số người trong nhóm phải từ 2 đến 20.")
            if any(d < 0 or d > 6 for d in days):
                raise OrderError("Ngày áp dụng buổi tối không hợp lệ.")
            hol = sorted({parse_holiday(x) for x in (data.get('holidays') or [])})
            if len(hol) > 300:
                raise OrderError("Danh sách ngày lễ quá dài.")
            new = {"vat_percent": vat, "lunch_end_hour": lunch, "group_size": group,
                   "dinner_days": days, "holidays": hol}

        old = get_settings(force=True)
        with transaction() as cur:
            if data.get('reset'):
                cur.execute("DELETE FROM app_settings WHERE key = ANY(%s)", (list(SETTING_KEYS),))
            else:
                values = {'cfg_vat_percent': str(new['vat_percent']), 'cfg_lunch_end_hour': str(new['lunch_end_hour']),
                          'cfg_group_size': str(new['group_size']),
                          'cfg_dinner_days': ','.join(map(str, new['dinner_days'])),
                          'cfg_holidays': ','.join(new['holidays'])}
                for k, v in values.items():
                    cur.execute("""INSERT INTO app_settings (key, value) VALUES (%s, %s)
                                   ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()""", (k, v))
    except OrderError as e:
        return fail(str(e))

    _SETTINGS_CACHE['val'] = None
    ch = []
    if old['vat_percent'] != new['vat_percent']:     ch.append(f"VAT {old['vat_percent']:g}% → {new['vat_percent']:g}%")
    if old['lunch_end_hour'] != new['lunch_end_hour']: ch.append(f"hết buổi trưa {old['lunch_end_hour']}h → {new['lunch_end_hour']}h")
    if old['group_size'] != new['group_size']:       ch.append(f"nhóm {old['group_size']} → {new['group_size']} người")
    if old['dinner_days'] != new['dinner_days']:     ch.append(f"ưu đãi tối {days_label(old['dinner_days'])} → {days_label(new['dinner_days'])}")
    if old['holidays'] != new['holidays']:           ch.append(f"ngày lễ {len(old['holidays'])} → {len(new['holidays'])} ngày")
    audit('Khôi phục cấu hình mặc định' if data.get('reset') else 'Đổi cấu hình', 'Cấu hình', '; '.join(ch) or 'không đổi')
    return jsonify({"success": True, "settings": new})


@bp.route('/api/manager/audit')
def api_manager_audit():
    q = (request.args.get('q') or '').strip()[:100]
    try:
        limit = max(1, min(int(request.args.get('limit') or 200), 500))
    except ValueError:
        limit = 200
    like = f"%{q}%"
    rows = query("""
        SELECT id, to_char(at, 'DD/MM/YYYY HH24:MI:SS') AS at, actor, action, target, detail
        FROM audit_log
        WHERE %s = '' OR action ILIKE %s OR target ILIKE %s OR detail ILIKE %s
        ORDER BY id DESC LIMIT %s""", (q, like, like, like, limit))
    return jsonify({"logs": [dict(r) for r in rows]})


@bp.route('/api/manager/staff')
def api_manager_staff():
    staffs = query("""
        SELECT s.id, s.name, s.role, s.avatar, s.is_active,
               (SELECT COUNT(*) FROM orders o WHERE o.staff_id = s.id)::int AS orders,
               EXISTS (SELECT 1 FROM orders o WHERE o.staff_id = s.id AND o.status = 'OPEN') AS busy
        FROM staffs s WHERE s.role <> 'Admin' ORDER BY s.id""")
    stations = query("SELECT id, name, description FROM stations ORDER BY id")
    return jsonify({"staffs": [dict(r) for r in staffs], "stations": [dict(r) for r in stations]})


@bp.route('/api/manager/staff/new', methods=['POST'])
def api_manager_staff_new():
    data = request.get_json() or {}
    try:
        name = clean_name(data.get('name'), 100)
        role = clean_name(data.get('role'), 50)
        if role in HIDDEN_ROLES:
            raise OrderError("Không tạo tài khoản Chủ/Admin ở đây.")
        pin = check_pin(data.get('pin'))
        avatar = str(data.get('avatar') or '').strip()[:200] or None
        with transaction() as cur:
            if pin_taken(cur, pin):
                raise OrderError("Mã PIN này đã có người dùng, hãy chọn PIN khác.")
            cur.execute("SELECT COALESCE(MAX(id::int), 0) + 1 AS n FROM staffs WHERE id ~ '^[0-9]+$'")
            new_id = '%02d' % cur.fetchone()['n']
            cur.execute("INSERT INTO staffs (id, name, role, pin, avatar) VALUES (%s, %s, %s, %s, %s)",
                        (new_id, name, role, pin_hash(pin), avatar))
    except OrderError as e:
        return fail(str(e))
    return jsonify({"success": True, "id": new_id})


@bp.route('/api/manager/staff/<staff_id>', methods=['POST'])
def api_manager_staff_edit(staff_id):
    data = request.get_json() or {}
    try:
        with transaction() as cur:
            cur.execute("SELECT id, role FROM staffs WHERE id = %s FOR UPDATE", (staff_id,))
            target = cur.fetchone()
            if not target:
                raise OrderError("Không tìm thấy nhân viên.", )
            if target['role'] == 'Admin' or (target['role'] == 'Chủ' and target['id'] != (current_mgr() or {}).get('id')):
                raise OrderError("Không sửa được tài khoản này.")
            if target['role'] in HIDDEN_ROLES and ('role' in data or data.get('is_active') is False):
                raise OrderError("Không đổi chức vụ hoặc khoá tài khoản Chủ/Admin.")
            if 'role' in data and clean_name(data['role'], 50) in HIDDEN_ROLES:
                raise OrderError("Không đặt chức vụ Chủ/Admin ở đây.")
            sets, params = [], []
            if 'name' in data:
                sets.append("name = %s"); params.append(clean_name(data['name'], 100))
            if 'role' in data:
                sets.append("role = %s"); params.append(clean_name(data['role'], 50))
            if 'avatar' in data:
                sets.append("avatar = %s"); params.append(str(data['avatar'] or '').strip()[:200] or None)
            if 'pin' in data:
                pin = check_pin(data['pin'])
                if pin_taken(cur, pin, except_staff=staff_id):
                    raise OrderError("Mã PIN này đã có người dùng, hãy chọn PIN khác.")
                sets.append("pin = %s"); params.append(pin_hash(pin))
            if 'is_active' in data:
                active = bool(data['is_active'])
                if not active:
                    cur.execute("SELECT 1 FROM orders WHERE staff_id = %s AND status = 'OPEN'", (staff_id,))
                    if cur.fetchone():
                        raise OrderError("Nhân viên này đang phụ trách bàn chưa thanh toán, chưa khoá được.")
                sets.append("is_active = %s"); params.append(active)
            if not sets:
                raise OrderError("Không có gì để cập nhật.")
            cur.execute(f"UPDATE staffs SET {', '.join(sets)} WHERE id = %s", (*params, staff_id))
    except OrderError as e:
        return fail(str(e))
    return jsonify({"success": True})


@bp.route('/api/manager/staff/<staff_id>/delete', methods=['POST'])
def api_manager_staff_delete(staff_id):
    with transaction() as cur:
        cur.execute("SELECT id, role FROM staffs WHERE id = %s FOR UPDATE", (staff_id,))
        target = cur.fetchone()
        if not target:
            return fail("Không tìm thấy nhân viên.", 404)
        if target['role'] in HIDDEN_ROLES:
            return fail("Không xoá được tài khoản Chủ/Admin.")
        cur.execute("SELECT 1 FROM orders WHERE staff_id = %s OR cashier_id = %s LIMIT 1", (staff_id, staff_id))
        if cur.fetchone():
            return fail("Nhân viên này đã có lịch sử phục vụ nên không xoá được. Hãy bấm KHOÁ để họ không đăng nhập nữa.")
        cur.execute("DELETE FROM staffs WHERE id = %s", (staff_id,))
    return jsonify({"success": True})


@bp.route('/api/manager/station/<station_id>/pin', methods=['POST'])
def api_manager_station_pin(station_id):
    try:
        pin = check_pin((request.get_json() or {}).get('pin'))
        with transaction() as cur:
            cur.execute("SELECT id FROM stations WHERE id = %s FOR UPDATE", (station_id,))
            if not cur.fetchone():
                raise OrderError("Không tìm thấy trạm bếp.")
            if pin_taken(cur, pin, except_station=station_id):
                raise OrderError("Mã PIN này đã có người dùng, hãy chọn PIN khác.")
            cur.execute("UPDATE stations SET pin = %s WHERE id = %s", (pin_hash(pin), station_id))
    except OrderError as e:
        return fail(str(e))
    return jsonify({"success": True})


@bp.route('/api/manager/tables')
def api_manager_tables():
    rows = query(f"""
        SELECT t.id, t.name, t.capacity, t.min_capacity, t.floor, t.type, t.is_active,
               EXISTS (SELECT 1 FROM orders o WHERE o.table_id = t.id AND o.status = 'OPEN') AS busy,
               (SELECT COUNT(*) FROM orders o WHERE o.table_id = t.id)::int AS orders
        FROM dining_tables t ORDER BY {NATURAL_TABLE_ORDER}""")
    return jsonify({"tables": [dict(r) for r in rows]})


@bp.route('/api/manager/table/new', methods=['POST'])
def api_manager_table_new():
    data = request.get_json() or {}
    try:
        tid = re.sub(r'\s', '', str(data.get('id') or '')).upper()
        if not re.fullmatch(r'[A-Z0-9]{1,10}', tid):
            raise OrderError("Mã bàn chỉ gồm chữ và số, tối đa 10 ký tự (VD: B12).")
        f = table_fields({**data, 'name': data.get('name') or tid})
        if f['min_capacity'] > f['capacity']:
            raise OrderError("Số khách tối thiểu không được lớn hơn số chỗ.")
        with transaction() as cur:
            cur.execute("SELECT 1 FROM dining_tables WHERE id = %s", (tid,))
            if cur.fetchone():
                raise OrderError("Mã bàn này đã tồn tại.")
            cur.execute("""INSERT INTO dining_tables (id, name, capacity, min_capacity, floor, type)
                           VALUES (%s, %s, %s, %s, %s, %s)""",
                        (tid, f['name'], f['capacity'], f['min_capacity'], f['floor'], f['type']))
    except OrderError as e:
        return fail(str(e))
    return jsonify({"success": True, "id": tid})


@bp.route('/api/manager/table/<table_id>', methods=['POST'])
def api_manager_table_edit(table_id):
    data = request.get_json() or {}
    if mgr_role() == 'Quản lí' and set(data) - {'is_active'}:
        return fail("Quản lí chỉ được ẩn hoặc hiện bàn.", 403)
    try:
        f = table_fields(data, partial=True)
        with transaction() as cur:
            cur.execute("SELECT * FROM dining_tables WHERE id = %s FOR UPDATE", (table_id,))
            t = cur.fetchone()
            if not t:
                raise OrderError("Không tìm thấy bàn.")
            cap = f.get('capacity', t['capacity'])
            mn = f.get('min_capacity', t['min_capacity'])
            if mn > cap:
                raise OrderError("Số khách tối thiểu không được lớn hơn số chỗ.")

            cur.execute("SELECT 1 FROM orders WHERE table_id = %s AND status = 'OPEN'", (table_id,))
            busy = bool(cur.fetchone())
            if busy and ('floor' in f and f['floor'] != t['floor']):
                raise OrderError("Bàn đang có khách, chưa đổi tầng được.")

            sets, params = [], []
            for k, v in f.items():
                sets.append(f"{k} = %s"); params.append(v)
            if 'is_active' in data:
                active = bool(data['is_active'])
                if not active:
                    if busy:
                        raise OrderError("Bàn đang có khách, chưa ẩn được.")
                sets.append("is_active = %s"); params.append(active)
            if not sets:
                raise OrderError("Không có gì để cập nhật.")
            cur.execute(f"UPDATE dining_tables SET {', '.join(sets)} WHERE id = %s", (*params, table_id))
    except OrderError as e:
        return fail(str(e))
    return jsonify({"success": True})


@bp.route('/api/manager/table/<table_id>/delete', methods=['POST'])
def api_manager_table_delete(table_id):
    with transaction() as cur:
        cur.execute("SELECT id FROM dining_tables WHERE id = %s FOR UPDATE", (table_id,))
        if not cur.fetchone():
            return fail("Không tìm thấy bàn.", 404)
        cur.execute("SELECT COUNT(*) AS n FROM orders WHERE table_id = %s", (table_id,))
        if cur.fetchone()['n']:
            return fail("Bàn này đã có lịch sử hoá đơn nên không xoá được. Hãy bấm ẨN.")
        cur.execute("DELETE FROM dining_tables WHERE id = %s", (table_id,))
    return jsonify({"success": True})


@bp.route('/api/manager/packages')
def api_manager_packages():
    rows = query("""
        SELECT p.id, p.name, p.price, p.valid_days, p.is_active,
               (SELECT COUNT(*) FROM package_items pi WHERE pi.package_id = p.id)::int AS items,
               (SELECT COUNT(*) FROM orders o WHERE o.status = 'OPEN'
                  AND (o.package_id = p.id OR o.drink_package_id = p.id))::int AS open_orders
        FROM packages p ORDER BY p.price""")
    out = []
    for r in rows:
        r = dict(r)
        r['days'] = parse_days(r.pop('valid_days'))
        r['kind'] = 'food' if r['price'] >= FOOD_PACKAGE_MIN_PRICE else 'drink'
        out.append(r)
    return jsonify({"packages": out, "food_min": FOOD_PACKAGE_MIN_PRICE})


@bp.route('/api/manager/package/<int:pid>', methods=['POST'])
def api_manager_package(pid):
    data = request.get_json() or {}
    try:
        with transaction() as cur:
            cur.execute("SELECT * FROM packages WHERE id = %s FOR UPDATE", (pid,))
            p = cur.fetchone()
            if not p:
                raise OrderError("Không tìm thấy gói.")
            sets, params = [], []

            if 'name' in data:
                sets.append("name = %s"); params.append(clean_name(data['name'], 100))

            if 'price' in data:
                try:
                    price = int(data['price'])
                except (TypeError, ValueError):
                    raise OrderError("Giá không hợp lệ.")
                if not 1000 <= price <= 5_000_000:
                    raise OrderError("Giá gói phải từ 1.000đ đến 5.000.000đ.")
                if (price >= FOOD_PACKAGE_MIN_PRICE) != (p['price'] >= FOOD_PACKAGE_MIN_PRICE):
                    raise OrderError("Gói đồ ăn phải từ %s trở lên, gói nước phải dưới mức đó."
                                     % f"{FOOD_PACKAGE_MIN_PRICE:,}đ".replace(',', '.'))
                cur.execute("SELECT 1 FROM packages WHERE price = %s AND id <> %s", (price, pid))
                if cur.fetchone():
                    raise OrderError("Đã có gói khác cùng mức giá này.")
                sets.append("price = %s"); params.append(price)

            if 'days' in data:
                raw = data['days'] or []
                try:
                    days = sorted({int(x) for x in raw})
                except (TypeError, ValueError):
                    raise OrderError("Ngày áp dụng không hợp lệ.")
                if any(d < 1 or d > 7 for d in days):
                    raise OrderError("Ngày áp dụng không hợp lệ.")
                # không chọn ngày nào hoặc chọn cả 7 ngày = áp dụng mọi ngày
                sets.append("valid_days = %s")
                params.append(None if not days or len(days) == 7 else ','.join(map(str, days)))

            if 'is_active' in data:
                active = bool(data['is_active'])
                if not active:
                    cur.execute("""SELECT COUNT(*)::int AS n FROM orders WHERE status = 'OPEN'
                                   AND (package_id = %s OR drink_package_id = %s)""", (pid, pid))
                    n = cur.fetchone()['n']
                    if n:
                        raise OrderError(f"Đang có {n} bàn dùng gói này, chưa tắt được.")
                sets.append("is_active = %s"); params.append(active)

            if not sets:
                raise OrderError("Không có gì để cập nhật.")
            cur.execute(f"UPDATE packages SET {', '.join(sets)} WHERE id = %s", (*params, pid))
    except OrderError as e:
        return fail(str(e))
    return jsonify({"success": True})


@bp.route('/api/manager/system/health')
def api_system_health():
    """Tình trạng hệ thống để Admin phát hiện lỗi: dữ liệu kẹt, chỉ mục thiếu, PIN chưa băm, khoá bí mật mặc định."""
    one = lambda sql, p=None: query(sql, p, one=True)['n']
    stuck = query("""
        SELECT t.id FROM dining_tables t
        WHERE (t.status = 'OCCUPIED' AND NOT EXISTS (SELECT 1 FROM orders o WHERE o.table_id = t.id AND o.status = 'OPEN'))
           OR (t.status <> 'OCCUPIED' AND EXISTS (SELECT 1 FROM orders o WHERE o.table_id = t.id AND o.status = 'OPEN'))
        ORDER BY t.id""")
    return jsonify({
        "success": True,
        "server_time": vn_now().strftime('%d/%m/%Y %H:%M:%S'),
        "db_tables": one("SELECT COUNT(*)::int AS n FROM information_schema.tables WHERE table_schema = 'public'"),
        "open_orders": one("SELECT COUNT(*)::int AS n FROM orders WHERE status = 'OPEN'"),
        "old_open_orders": one("SELECT COUNT(*)::int AS n FROM orders WHERE status = 'OPEN' AND created_at < NOW() - INTERVAL '12 hours'"),
        "stuck_tables": [r['id'] for r in stuck],
        "old_calls": one("SELECT COUNT(*)::int AS n FROM service_calls WHERE status = 'OPEN' AND created_at < NOW() - INTERVAL '2 hours'"),
        "unique_indexes": one("""SELECT COUNT(*)::int AS n FROM pg_indexes
                                 WHERE indexname IN ('uq_one_open_order_per_table', 'uq_service_call_open')"""),
        "plain_pins": one("""SELECT (SELECT COUNT(*) FROM staffs WHERE pin NOT LIKE 'pbkdf2:%%' AND pin NOT LIKE 'scrypt:%%')
                                  + (SELECT COUNT(*) FROM stations WHERE pin NOT LIKE 'pbkdf2:%%' AND pin NOT LIKE 'scrypt:%%') AS n"""),
        "default_secret": current_app.config.get('SECRET_IS_DEFAULT', False),
    })


@bp.route('/api/manager/system/cleanup', methods=['POST'])
def api_system_cleanup():
    """Sửa dữ liệu kẹt: trạng thái bàn lệch với đơn đang mở; yêu cầu gọi nhân viên bị bỏ quên quá 2 giờ."""
    with transaction() as cur:
        cur.execute("""UPDATE dining_tables SET status = 'AVAILABLE'
                       WHERE status = 'OCCUPIED'
                         AND NOT EXISTS (SELECT 1 FROM orders o WHERE o.table_id = dining_tables.id AND o.status = 'OPEN')""")
        freed = cur.rowcount
        cur.execute("""UPDATE dining_tables SET status = 'OCCUPIED'
                       WHERE status <> 'OCCUPIED'
                         AND EXISTS (SELECT 1 FROM orders o WHERE o.table_id = dining_tables.id AND o.status = 'OPEN')""")
        taken = cur.rowcount
        cur.execute("""UPDATE service_calls SET status = 'DONE', done_at = NOW(), done_by = 'Admin (dọn tự động)'
                       WHERE status = 'OPEN' AND created_at < NOW() - INTERVAL '2 hours'""")
        calls = cur.rowcount
    audit('Dọn dữ liệu kẹt', '', f"giải phóng {freed} bàn, đánh dấu {taken} bàn đang có khách, đóng {calls} yêu cầu cũ")
    return jsonify({"success": True, "freed_tables": freed, "marked_tables": taken, "closed_calls": calls})


@bp.route('/api/manager/system/accounts')
def api_system_accounts():
    """Danh sách tài khoản (không có PIN) để Admin chọn đặt lại PIN."""
    staffs = query("SELECT id, name, role, is_active FROM staffs ORDER BY id")
    stations = query("SELECT id, name FROM stations ORDER BY id")
    return jsonify({"success": True, "staffs": [dict(r) for r in staffs], "stations": [dict(r) for r in stations]})


@bp.route('/api/manager/system/reset-pin', methods=['POST'])
def api_system_reset_pin():
    """Admin đặt lại PIN cho bất kỳ tài khoản nào (khi người dùng quên PIN)."""
    data = request.get_json() or {}
    kind = 'station' if data.get('kind') == 'station' else 'staff'
    acc_id = str(data.get('id') or '')
    try:
        pin = check_pin(data.get('pin'))
        with transaction() as cur:
            cur.execute(f"SELECT id FROM {'stations' if kind == 'station' else 'staffs'} WHERE id = %s FOR UPDATE", (acc_id,))
            if not cur.fetchone():
                raise OrderError("Không tìm thấy tài khoản.")
            if pin_taken(cur, pin, except_staff=acc_id if kind == 'staff' else None,
                         except_station=acc_id if kind == 'station' else None):
                raise OrderError("Mã PIN này đã có người dùng, hãy chọn PIN khác.")
            cur.execute(f"UPDATE {'stations' if kind == 'station' else 'staffs'} SET pin = %s WHERE id = %s",
                        (pin_hash(pin), acc_id))
    except OrderError as e:
        return fail(str(e))
    return jsonify({"success": True})


@bp.route('/api/qr-base')
def api_qr_base():
    """Địa chỉ gốc để in vào mã QR bàn.
    - Đặt biến môi trường PUBLIC_URL (vd https://gyu-qr.onrender.com) thì dùng đúng địa chỉ đó.
    - Đang mở bằng localhost / 127.0.0.1 (chạy thử trên máy) thì đổi sang IP mạng nội bộ để điện thoại quét được.
    - Còn lại dùng chính địa chỉ đang mở (Render)."""
    public = (os.environ.get('PUBLIC_URL') or '').strip().rstrip('/')
    if public:
        return jsonify({"base": public, "source": "PUBLIC_URL"})
    host = request.host.split(':')[0]
    if host in ('localhost', '127.0.0.1', '::1'):
        port = request.host.split(':')[1] if ':' in request.host else '5000'
        return jsonify({"base": f"http://{lan_ip()}:{port}", "source": "LAN"})
    return jsonify({"base": request.host_url.rstrip('/'), "source": "HOST"})


@bp.route('/api/qr-tokens')
def api_qr_tokens():
    """Mã xác thực QR của từng bàn — chỉ nhân viên/quản lí đã đăng nhập mới lấy được."""
    if not (session.get('staff') or manager_ok()):
        return fail("Hết phiên đăng nhập, hãy đăng nhập lại.", 401)
    rows = query("SELECT id FROM dining_tables")
    return jsonify({"success": True, "tokens": {r['id']: qr_token(r['id']) for r in rows}})


@bp.route('/qr-ban')
def qr_print_page():
    """Trang in mã QR cho từng bàn (chỉ quản lí)."""
    if not manager_ok():
        return redirect('/quanli')
    return render_template('manager/qr_ban.html')


@bp.route('/api/manager/payment')
def api_manager_payment_get():
    return jsonify(payment_config())


@bp.route('/api/manager/payment', methods=['POST'])
def api_manager_payment_save():
    data = request.get_json() or {}
    try:
        bank = str(data.get('bank_id') or '').strip().upper()
        acc = re.sub(r'\s', '', str(data.get('account') or ''))
        holder = ' '.join(str(data.get('holder') or '').split()).upper()[:60]
        if bank or acc or holder:
            if not re.fullmatch(r'[A-Z0-9]{2,12}', bank):
                raise OrderError("Hãy chọn ngân hàng.")
            if not re.fullmatch(r'\d{6,20}', acc):
                raise OrderError("Số tài khoản chỉ gồm 6–20 chữ số.")
            if not holder:
                raise OrderError("Hãy nhập tên chủ tài khoản.")
        with transaction() as cur:
            for k, v in (('cfg_bank_id', bank), ('cfg_bank_account', acc), ('cfg_bank_holder', holder)):
                cur.execute("""INSERT INTO app_settings (key, value) VALUES (%s, %s)
                               ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()""", (k, v))
        audit('Đổi tài khoản nhận chuyển khoản', bank or '(xoá)', f"STK ***{acc[-4:]}" if acc else '')
    except OrderError as e:
        return fail(str(e))
    return jsonify({"success": True})
