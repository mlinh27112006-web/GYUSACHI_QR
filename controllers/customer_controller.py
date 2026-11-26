"""Người phụ trách: Thúy Hằng
Mô tả: Khách quét QR: trang gọi món tại bàn, xem tạm tính, gọi nhân viên / xin tính tiền.
"""

from flask import render_template, request, jsonify, redirect, url_for, session, Blueprint

from core.auth import manager_ok, qr_ok, qr_token, table_access_ok
from core.db import query, transaction
from core.helpers import OrderError, fail
from models.billing_model import compute_bill, load_order_for_bill
from models.order_model import order_detail

bp = Blueprint('customer', __name__)


@bp.route('/api/table/<table_id>/summary')
def api_table_summary(table_id):
    """Khách xem trên trang QR: đã gọi bao nhiêu phần + tạm tính. Cùng công thức với màn hình thu ngân
    (có VAT, có ưu đãi nhóm nếu được áp dụng) nhưng chỉ là TẠM TÍNH: thu ngân có thể chỉnh số khách / ưu đãi."""
    if not table_access_ok(table_id):
        return fail("Mã QR không hợp lệ, hãy quét lại mã trên bàn.", 403)
    row = query("SELECT id FROM orders WHERE table_id = %s AND status = 'OPEN'", (table_id.upper(),), one=True)
    if not row:
        return jsonify({"success": True, "summary": None})
    o, items = load_order_for_bill(row['id'])
    b = compute_bill(o, items)

    live = [i for i in items if i['status'] != 'CANCELLED']
    top = [i for i in live if i['parent_id'] is None]            # PACKAGE / ALACARTE / COMBO (mỗi combo = 1 phần)
    served = 0
    for i in top:
        kids = [c for c in live if c['parent_id'] == i['id']]
        if (kids and all(c['status'] == 'DONE' for c in kids)) or (not kids and i['status'] == 'DONE'):
            served += i['qty']
    dishes = sum(i['qty'] for i in top)

    return jsonify({"success": True, "summary": {
        "dishes": dishes, "served": served, "waiting": dishes - served,
        "guests": b['guests'],
        "food_name": b['food_name'], "food_price": b['food_price'], "food_amount": b['food_amount'],
        "drink_name": b['drink_name'], "drink_price": b['drink_price'], "drink_amount": b['drink_amount'],
        "lines": [{"name": l['name'], "qty": l['qty'], "amount": l['amount']} for l in b['lines']],
        "discount": b['discount'], "promo_free": b['promo_free'],
        "vat": b['vat'], "total": b['total']}})


@bp.route('/api/orders/by-table/<table_id>')
def api_order_by_table(table_id):
    if not table_access_ok(table_id):
        return fail("Mã QR không hợp lệ, hãy quét lại mã trên bàn.", 403)
    row = query("SELECT id FROM orders WHERE table_id = %s AND status = 'OPEN'",
                (table_id,), one=True)
    return jsonify({"order": order_detail(row['id']) if row else None})


@bp.route('/ban/<table_id>')
def table_self_order(table_id):
    t = query("SELECT id, name FROM dining_tables WHERE id = %s AND is_active", (table_id.upper(),), one=True)
    if not t:
        return redirect(url_for('auth.home'))
    key = request.args.get('k') or ''
    if not qr_ok(t['id'], key):
        if session.get('staff') or manager_ok():
            key = qr_token(t['id'])                    # nhân viên xem thử trang của bàn
        else:
            return ("<meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
                    "<body style='font-family:sans-serif;text-align:center;padding:40px'>"
                    "<h2>Mã QR không hợp lệ</h2><p>Vui lòng quét lại mã QR trên bàn hoặc gọi nhân viên.</p></body>"), 403
    # dùng goimon.html; nếu thư mục templates chỉ có bản đổi tên cũ goimon_ban.html thì dùng bản đó
    return render_template(['customer/goimon.html', 'customer/goimon_ban.html'], table=dict(t), table_key=key)


@bp.route('/api/service-call/status')
def api_service_call_status():
    """Trạng thái yêu cầu đang chờ của 1 bàn (để trang khách hiện 'đã gọi, nhân viên sẽ tới ngay')."""
    if not table_access_ok(request.args.get('table_id')):
        return fail("Mã QR không hợp lệ, hãy quét lại mã trên bàn.", 403)
    rows = query("SELECT kind FROM service_calls WHERE table_id = %s AND status = 'OPEN'", (request.args.get('table_id'),))
    return jsonify({"open": sorted({r['kind'] for r in rows})})


@bp.route('/api/service-call', methods=['POST'])
def api_service_call():
    """Khách bấm Gọi nhân viên (CALL) hoặc Xin tính tiền (BILL). Bấm lặp lại khi chưa ai xử lý thì không tạo thêm."""
    data = request.get_json() or {}
    kind = data.get('kind')
    if not table_access_ok(data.get('table_id')):
        return fail("Mã QR không hợp lệ, hãy quét lại mã trên bàn.", 403)
    try:
        if kind not in ('CALL', 'BILL'):
            raise OrderError("Yêu cầu không hợp lệ.")
        with transaction() as cur:
            cur.execute("SELECT id FROM dining_tables WHERE id = %s AND is_active", (data.get('table_id'),))
            if not cur.fetchone():
                raise OrderError("Không tìm thấy bàn.")
            cur.execute("SELECT id FROM orders WHERE table_id = %s AND status = 'OPEN'", (data['table_id'],))
            o = cur.fetchone()
            if kind == 'BILL' and not o:
                raise OrderError("Bàn chưa có món nào để tính tiền.")
            cur.execute("SELECT 1 FROM service_calls WHERE table_id = %s AND kind = %s AND status = 'OPEN'", (data['table_id'], kind))
            if not cur.fetchone():
                cur.execute("""SELECT 1 FROM service_calls WHERE table_id = %s AND kind = %s
                               AND created_at > NOW() - INTERVAL '30 seconds'""", (data['table_id'], kind))
                if cur.fetchone():
                    raise OrderError("Bạn vừa gửi yêu cầu xong, vui lòng đợi giây lát rồi gửi lại.")
                cur.execute("INSERT INTO service_calls (table_id, order_id, kind) VALUES (%s, %s, %s)",
                            (data['table_id'], o['id'] if o else None, kind))
    except OrderError as e:
        return fail(str(e))
    except Exception as e:
        if getattr(e, 'pgcode', None) == '23505':       # đã có yêu cầu đang mở cùng loại (gửi trùng cùng lúc)
            return jsonify({"success": True, "already": True})
        raise
    return jsonify({"success": True})
