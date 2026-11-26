"""Người phụ trách: Hồng Ngọc
Mô tả: Quầy thu ngân: đăng nhập quầy, hoá đơn, thanh toán nhiều hình thức, lịch sử.
"""

from flask import render_template, request, jsonify, session, Blueprint

from core.auth import lock_message, pin_check, pin_failed, pin_locked, pin_ok
from core.db import query, transaction
from core.helpers import OrderError, fail
from models.billing_model import PAY_METHODS, compute_bill, load_order_for_bill, parse_promo, pending_count
from models.settings_model import payment_config

bp = Blueprint('cashier', __name__)


@bp.route('/thungan')
def thungan():
    return render_template('cashier/thungan.html')


CASHIER_DEFAULT_NAME = 'Phương'      # người thu ngân mặc định (chọn sẵn ở màn hình đăng nhập quầy)


def default_cashier_id():
    row = query("SELECT id FROM staffs WHERE is_active AND name LIKE %s ORDER BY id LIMIT 1",
                (f"%{CASHIER_DEFAULT_NAME}%",), one=True)
    return row['id'] if row else None


@bp.route('/api/cashier/staff')
def api_cashier_staff():
    """Danh sách nhân viên để chọn "ai đang thu ngân" ở màn hình đăng nhập quầy (không có PIN)."""
    rows = query("SELECT id, name, role FROM staffs WHERE is_active AND role NOT IN ('Chủ', 'Admin') ORDER BY id")
    return jsonify({"staff": [dict(r) for r in rows], "default_id": default_cashier_id()})


@bp.route('/api/cashier/login', methods=['POST'])
def api_cashier_login():
    """Thu ngân chọn tên mình rồi nhập PIN 4 số của chính nhân viên đó (bảng staffs)."""
    data = request.get_json() or {}
    pin = str(data.get('pin', '')).strip()
    left = pin_locked('cashier')
    if left:
        return fail(lock_message(left), 429)

    sid = str(data.get('staff_id') or '').strip() or default_cashier_id()
    staff = query("SELECT id, name, pin FROM staffs WHERE id = %s AND is_active AND role NOT IN ('Chủ', 'Admin')", (sid,), one=True) if sid else None
    if not staff:
        return fail("Hãy chọn người thu ngân.")
    if not pin_check(staff['pin'], pin):
        pin_failed('cashier')
        return fail("Mã PIN không đúng.", 401)
    pin_ok('cashier')
    session.permanent = True
    session.pop('station', None)
    session['cashier'] = True
    session['cashier_id'] = staff['id']          # ghi vào hoá đơn (orders.cashier_id) khi thanh toán
    return jsonify({"success": True, "id": staff['id'], "name": staff['name']})


@bp.route('/api/cashier/me')
def api_cashier_me():
    if not session.get('cashier'):
        return jsonify({"logged_in": False})
    staff = query("SELECT id, name FROM staffs WHERE id = %s", (session.get('cashier_id'),), one=True)
    return jsonify({"logged_in": True, "id": staff['id'] if staff else None, "name": staff['name'] if staff else None})


@bp.route('/api/cashier/logout', methods=['POST'])
def api_cashier_logout():
    session.pop('cashier', None)
    session.pop('cashier_id', None)
    return jsonify({"success": True})


@bp.route('/api/cashier/orders')
def api_cashier_orders():
    """Các bàn đang có khách + tạm tính."""
    out = []
    try:
        billing = {r['table_id'] for r in query("SELECT table_id FROM service_calls WHERE status = 'OPEN' AND kind = 'BILL'")}
    except Exception:                                  # chưa chạy file 22
        billing = set()
    for r in query("SELECT id FROM orders WHERE status = 'OPEN' ORDER BY created_at"):
        o, items = load_order_for_bill(r['id'])
        b = compute_bill(o, items)
        out.append({"id": o['id'], "table_id": o['table_id'], "guests": o['guests'],
                    "opened_at": o['opened_at'], "package_name": o['package_name'],
                    "total": b['total'], "pending": pending_count(items),
                    "bill_requested": o['table_id'] in billing})
    return jsonify({"orders": out})


@bp.route('/api/cashier/bill/<int:order_id>')
def api_cashier_bill(order_id):
    o, items = load_order_for_bill(order_id)
    if not o:
        return fail("Không tìm thấy đơn.", 404)
    try:
        guests = int(request.args.get('guests') or o['guests'])
    except ValueError:
        return fail("Số khách không hợp lệ.")
    if not 1 <= guests <= 60:
        return fail("Số khách phải từ 1 đến 60.")
    b = compute_bill(o, items, guests, parse_promo(request.args.get('promo')), request.args.get('voucher') or None)
    b.update({"order_id": o['id'], "table_id": o['table_id'], "status": o['status'],
              "opened_at": o['opened_at'], "pending": pending_count(items)})
    # thông tin in trên phiếu: tầng, nhân viên phục vụ, giờ vào đầy đủ
    extra = query("""SELECT t.floor, s.name AS staff_name,
                            to_char(o.created_at, 'DD/MM/YYYY') AS open_date,
                            to_char(o.created_at, 'HH24:MI') AS open_time
                     FROM orders o LEFT JOIN dining_tables t ON t.id = o.table_id
                     LEFT JOIN staffs s ON s.id = o.staff_id WHERE o.id = %s""", (o['id'],), one=True)
    if extra:
        b.update({"floor": extra['floor'], "staff_name": extra['staff_name'],
                  "open_date": extra['open_date'], "open_time": extra['open_time']})
    return jsonify({"success": True, "bill": b})


@bp.route('/api/cashier/pay/<int:order_id>', methods=['POST'])
def api_cashier_pay(order_id):
    data = request.get_json() or {}
    raw = data.get('payments')
    if raw is None:                                   # tương thích kiểu cũ: một hình thức, thu đủ
        raw = [{"method": data.get('method'), "amount": None}]
    if not isinstance(raw, list) or not raw:
        return fail("Hãy chọn hình thức thanh toán.")
    for p_ in raw:
        if not isinstance(p_, dict) or p_.get('method') not in PAY_METHODS:
            return fail("Hãy chọn hình thức thanh toán.")

    try:
        with transaction() as cur:
            if not session.get('cashier'):
                raise OrderError("Hết phiên đăng nhập, hãy đăng nhập lại quầy thu ngân.")

            o, items = load_order_for_bill(order_id, cur)
            if not o:
                raise OrderError("Không tìm thấy đơn.")
            if o['status'] != 'OPEN':
                raise OrderError("Đơn này đã thanh toán rồi.")

            if pending_count(items) and not data.get('force'):
                raise OrderError("PENDING")

            try:
                guests = int(data.get('guests') or o['guests'])
            except (TypeError, ValueError):
                raise OrderError("Số khách không hợp lệ.")
            if not 1 <= guests <= 60:
                raise OrderError("Số khách phải từ 1 đến 60.")

            b = compute_bill(o, items, guests, parse_promo(data.get('promo')), data.get('voucher') or None)
            if b['voucher_error']:
                raise OrderError(b['voucher_error'])

            # mỗi khoản thu = 1 dòng order_payments; tổng các khoản phải đúng bằng số phải trả
            pays = []
            for p_ in raw:
                try:
                    amt = int(p_['amount']) if p_.get('amount') not in (None, '') else (b['total'] if len(raw) == 1 else 0)
                except (TypeError, ValueError):
                    raise OrderError("Số tiền khoản thu không hợp lệ.")
                if amt <= 0:
                    raise OrderError("Mỗi khoản thu phải lớn hơn 0.")
                pays.append((p_['method'], amt))
            if sum(a_ for _, a_ in pays) != b['total']:
                raise OrderError("Tổng các khoản thu (%s) phải bằng số phải trả (%s)." % (sum(a_ for _, a_ in pays), b['total']))
            method = pays[0][0] if len({m_ for m_, _ in pays}) == 1 else 'MIXED'

            # người đang thu ngân (chọn lúc đăng nhập quầy); phiên cũ chưa có thì để trống như trước
            cur.execute("SELECT id FROM staffs WHERE id = %s", (session.get('cashier_id'),))
            cashier = cur.fetchone()

            cur.execute("""
                UPDATE orders SET status = 'CLOSED', closed_at = NOW(), paid_at = NOW(),
                       guests = %s, payment_method = %s, cashier_id = %s,
                       food_amount = %s, drink_amount = %s, extra_amount = %s,
                       discount = %s, vat_amount = %s, total = %s, promo_note = %s
                WHERE id = %s
            """, (guests, method, cashier['id'] if cashier else None, b['food_amount'], b['drink_amount'], b['extra_amount'],
                  b['discount'], b['vat'], b['total'], b['promo_note'], order_id))
            for m_, a_ in pays:
                cur.execute("""INSERT INTO order_payments (order_id, method, amount, cashier_id)
                               VALUES (%s, %s, %s, %s)""", (order_id, m_, a_, cashier['id'] if cashier else None))
            cur.execute("UPDATE dining_tables SET status = 'AVAILABLE' WHERE id = %s", (o['table_id'],))

    except OrderError as e:
        if str(e) == "PENDING":
            return jsonify({"success": False, "pending": True,
                            "message": "Bàn còn món bếp chưa làm xong. Vẫn thanh toán?"}), 409
        return fail(str(e))

    return jsonify({"success": True, "total": b['total']})


@bp.route('/api/cashier/history')
def api_cashier_history():
    """Các hoá đơn đã thanh toán trong hôm nay + tổng kết."""
    rows = query("""
        SELECT o.id, o.table_id, o.guests, o.payment_method, o.total, o.discount,
               to_char(o.paid_at, 'HH24:MI') AS paid_time, COALESCE(s.name, 'Thu ngân') AS cashier
        FROM orders o LEFT JOIN staffs s ON s.id = o.cashier_id
        WHERE o.paid_at::date = CURRENT_DATE AND o.voided_at IS NULL
        ORDER BY o.paid_at DESC
    """)
    rows = [dict(r) for r in rows]
    by_method = {m: 0 for m in PAY_METHODS}
    for r in query("""SELECT p.method, COALESCE(SUM(p.amount), 0)::bigint AS s
                      FROM order_payments p JOIN orders o ON o.id = p.order_id
                      WHERE o.paid_at::date = CURRENT_DATE AND o.voided_at IS NULL GROUP BY p.method"""):
        by_method[r['method']] = int(r['s'])
    return jsonify({"orders": rows, "count": len(rows),
                    "revenue": sum(r['total'] for r in rows), "by_method": by_method})


@bp.route('/api/cashier/payment-config')
def api_cashier_payment_config():
    if not session.get('cashier'):
        return fail("Chưa đăng nhập thu ngân.", 401)
    return jsonify(payment_config())
