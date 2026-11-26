"""Người phụ trách: Hồng Ngọc
Mô tả: Báo cáo của quản lí: tổng quan, doanh thu, hoá đơn, thống kê món, huỷ/khôi phục hoá đơn, xuất CSV.
"""

import csv
import io
from datetime import timedelta

from flask import request, jsonify, Response, Blueprint

from core.audit import audit
from core.auth import mgr_role
from core.db import query, transaction
from core.helpers import date_range, fail, vn_now, vnd
from models.report_model import PAID, SafeCsv, daily_series
from models.settings_model import get_settings

bp = Blueprint('report', __name__)


@bp.route('/api/manager/overview')
def api_manager_overview():
    periods = {
        "today": "o.paid_at >= CURRENT_DATE",
        "week":  "o.paid_at >= date_trunc('week', CURRENT_DATE)",
        "month": "o.paid_at >= date_trunc('month', CURRENT_DATE)",
    }
    out = {}
    for key, cond in periods.items():
        r = query(f"""SELECT COALESCE(SUM(o.total), 0)::bigint AS revenue, COUNT(*)::int AS bills,
                             COALESCE(SUM(o.guests), 0)::int AS guests
                      FROM orders o WHERE {PAID} AND {cond}""", one=True)
        r = dict(r)
        r['avg'] = int(r['revenue'] / r['bills']) if r['bills'] else 0
        out[key] = r

    open_row = query("""SELECT COUNT(*)::int AS tables, COALESCE(SUM(guests), 0)::int AS guests
                        FROM orders WHERE status = 'OPEN'""", one=True)
    all_tables = query("SELECT COUNT(*)::int AS n FROM dining_tables WHERE is_active", one=True)['n']

    today = vn_now().date()
    series = daily_series((today - timedelta(days=13)).isoformat(), today.isoformat())

    top = query(f"""
        SELECT oi.name, SUM(oi.qty)::int AS qty
        FROM order_items oi JOIN orders o ON o.id = oi.order_id
        WHERE {PAID} AND o.paid_at >= CURRENT_DATE AND oi.status <> 'CANCELLED'
          AND oi.kind IN ('PACKAGE', 'ALACARTE', 'COMBO_PART')
        GROUP BY oi.name ORDER BY qty DESC, oi.name LIMIT 5""")

    resp = {**out, "open": dict(open_row), "total_tables": all_tables,
            "series": series, "top_today": [dict(r) for r in top]}
    if mgr_role() == 'Quản lí':                      # doanh thu tuần/tháng và biểu đồ là của Chủ
        for k in ('week', 'month', 'series'):
            resp.pop(k, None)
    return jsonify(resp)


@bp.route('/api/manager/report')
def api_manager_report():
    d_from, d_to = date_range()
    rng = "o.paid_at::date BETWEEN %s AND %s"
    p = (d_from, d_to)

    s = dict(query(f"""
        SELECT COALESCE(SUM(o.total), 0)::bigint AS revenue, COUNT(*)::int AS bills,
               COALESCE(SUM(o.guests), 0)::int AS guests,
               COALESCE(SUM(o.food_amount), 0)::bigint AS food,
               COALESCE(SUM(o.drink_amount), 0)::bigint AS drink,
               COALESCE(SUM(o.extra_amount), 0)::bigint AS extra,
               COALESCE(SUM(o.discount), 0)::bigint AS discount,
               COALESCE(SUM(o.vat_amount), 0)::bigint AS vat
        FROM orders o WHERE {PAID} AND {rng}""", p, one=True))
    s['avg'] = int(s['revenue'] / s['bills']) if s['bills'] else 0

    by_method = [dict(r) for r in query(f"""
        SELECT p.method AS name, COALESCE(SUM(p.amount), 0)::bigint AS revenue, COUNT(DISTINCT p.order_id)::int AS bills
        FROM order_payments p JOIN orders o ON o.id = p.order_id
        WHERE {PAID} AND {rng} GROUP BY p.method ORDER BY revenue DESC""", p)]

    by_package = [dict(r) for r in query(f"""
        SELECT COALESCE(pk.name, 'Chỉ gọi lẻ') AS name, COALESCE(SUM(o.total), 0)::bigint AS revenue,
               COUNT(*)::int AS bills, COALESCE(SUM(o.guests), 0)::int AS guests
        FROM orders o LEFT JOIN packages pk ON pk.id = o.package_id
        WHERE {PAID} AND {rng} GROUP BY pk.name, pk.price ORDER BY pk.price NULLS FIRST""", p)]

    by_shift = [dict(r) for r in query(f"""
        SELECT CASE WHEN EXTRACT(HOUR FROM o.created_at) < {int(get_settings()['lunch_end_hour'])} THEN 'Trưa' ELSE 'Tối' END AS name,
               COALESCE(SUM(o.total), 0)::bigint AS revenue, COUNT(*)::int AS bills
        FROM orders o WHERE {PAID} AND {rng} GROUP BY 1 ORDER BY 1 DESC""", p)]

    invoices = [dict(r) for r in query(f"""
        SELECT o.id, o.table_id, o.guests, o.payment_method, o.total, o.discount,
               to_char(o.paid_at, 'DD/MM HH24:MI') AS paid_time, COALESCE(pk.name, 'Chỉ gọi lẻ') AS package
        FROM orders o LEFT JOIN packages pk ON pk.id = o.package_id
        WHERE {PAID} AND {rng} ORDER BY o.paid_at DESC LIMIT 300""", p)]

    voided = [dict(r) for r in query("""
        SELECT o.id, o.table_id, o.total, o.void_reason,
               to_char(o.paid_at, 'DD/MM HH24:MI') AS paid_time, to_char(o.voided_at, 'DD/MM HH24:MI') AS voided_time
        FROM orders o
        WHERE o.status = 'CLOSED' AND o.paid_at IS NOT NULL AND o.voided_at IS NOT NULL
          AND o.paid_at::date BETWEEN %s AND %s
        ORDER BY o.voided_at DESC LIMIT 100""", p)]

    return jsonify({"from": d_from, "to": d_to, "summary": s, "by_method": by_method,
                    "by_package": by_package, "by_shift": by_shift,
                    "series": daily_series(d_from, d_to), "invoices": invoices, "voided": voided})


@bp.route('/api/manager/invoice/<int:order_id>')
def api_manager_invoice(order_id):
    o = query("""
        SELECT o.id, o.table_id, o.guests, o.payment_method, o.status, o.promo_note,
               to_char(o.created_at, 'DD/MM HH24:MI') AS opened_at,
               to_char(o.paid_at, 'DD/MM HH24:MI') AS paid_at,
               o.food_amount, o.drink_amount, o.extra_amount, o.discount, o.vat_amount, o.total,
               (o.voided_at IS NOT NULL) AS voided, o.void_reason,
               to_char(o.voided_at, 'DD/MM HH24:MI') AS voided_time,
               pk.name AS package_name, pk.price AS package_price,
               dk.name AS drink_name,   dk.price AS drink_price
        FROM orders o
        LEFT JOIN packages pk ON pk.id = o.package_id
        LEFT JOIN packages dk ON dk.id = o.drink_package_id
        WHERE o.id = %s""", (order_id,), one=True)
    if not o:
        return fail("Không tìm thấy hoá đơn.", 404)
    lines = query("""
        SELECT name, qty, unit_price::int AS unit_price, (qty * unit_price)::int AS amount
        FROM order_items
        WHERE order_id = %s AND parent_id IS NULL AND kind IN ('ALACARTE', 'COMBO') AND status <> 'CANCELLED'
        ORDER BY id""", (order_id,))
    inv = dict(o)
    # Đã thanh toán: đơn giá lấy theo số tiền đã lưu (không đổi dù sau này quản lí sửa giá gói)
    if inv.get('guests') and inv.get('food_amount') is not None:
        inv['package_price'] = inv['food_amount'] // inv['guests']
    if inv.get('guests') and inv.get('drink_amount') is not None:
        inv['drink_price'] = inv['drink_amount'] // inv['guests']
    inv['payments'] = [dict(r) for r in query(
        "SELECT method, amount::int AS amount FROM order_payments WHERE order_id = %s ORDER BY id", (order_id,))]
    return jsonify({"success": True, "invoice": inv, "lines": [dict(l) for l in lines]})


@bp.route('/api/manager/dishes')
def api_manager_dishes():
    d_from, d_to = date_range()
    p = (d_from, d_to)
    base = f"""FROM order_items oi JOIN orders o ON o.id = oi.order_id
               WHERE {PAID} AND o.paid_at::date BETWEEN %s AND %s"""

    buffet = query(f"""SELECT oi.name, SUM(oi.qty)::int AS qty {base}
                       AND oi.kind = 'PACKAGE' AND oi.status <> 'CANCELLED'
                       GROUP BY oi.name ORDER BY qty DESC, oi.name LIMIT 15""", p)

    paid_items = query(f"""
        SELECT oi.name, COALESCE(MAX(a.category), '') AS category, SUM(oi.qty)::int AS qty,
               SUM(oi.qty * oi.unit_price)::bigint AS revenue
        {base} AND oi.parent_id IS NULL AND oi.kind IN ('ALACARTE', 'COMBO') AND oi.status <> 'CANCELLED'
        GROUP BY oi.name ORDER BY revenue DESC, oi.name""".replace(
        "FROM order_items oi JOIN orders o ON o.id = oi.order_id",
        "FROM order_items oi JOIN orders o ON o.id = oi.order_id LEFT JOIN alacarte_items a ON a.name = oi.name"), p)
    paid_items = [dict(r) for r in paid_items]

    by_cat = {}
    for r in paid_items:
        c = r['category'] or 'Khác'
        by_cat[c] = by_cat.get(c, 0) + r['revenue']
    by_category = sorted(({"name": k, "revenue": v} for k, v in by_cat.items()),
                         key=lambda x: -x['revenue'])

    cancelled = query(f"""SELECT oi.name, SUM(oi.qty)::int AS qty {base}
                          AND oi.parent_id IS NULL AND oi.status = 'CANCELLED'
                          GROUP BY oi.name ORDER BY qty DESC, oi.name LIMIT 15""", p)
    cancelled_total = query(f"""SELECT COALESCE(SUM(oi.qty), 0)::int AS n {base}
                                AND oi.parent_id IS NULL AND oi.status = 'CANCELLED'""", p, one=True)['n']

    return jsonify({"from": d_from, "to": d_to,
                    "buffet": [dict(r) for r in buffet],
                    "paid_top": paid_items[:15], "by_category": by_category,
                    "cancelled": [dict(r) for r in cancelled], "cancelled_total": cancelled_total})


@bp.route('/api/manager/invoice/<int:order_id>/void', methods=['POST'])
def api_manager_invoice_void(order_id):
    reason = ' '.join(str((request.get_json() or {}).get('reason') or '').split())[:300]
    if len(reason) < 3:
        return fail("Hãy nhập lí do huỷ hoá đơn (ít nhất 3 ký tự).")
    with transaction() as cur:
        cur.execute("SELECT id, table_id, total, status, paid_at, voided_at FROM orders WHERE id = %s FOR UPDATE",
                    (order_id,))
        o = cur.fetchone()
        if not o:
            return fail("Không tìm thấy hoá đơn.", 404)
        if o['status'] != 'CLOSED' or not o['paid_at']:
            return fail("Hoá đơn này chưa thanh toán.")
        if o['voided_at']:
            return fail("Hoá đơn này đã được huỷ rồi.")
        cur.execute("UPDATE orders SET voided_at = NOW(), void_reason = %s WHERE id = %s", (reason, order_id))
    audit('Huỷ hoá đơn', f"#{order_id} · bàn {o['table_id']}", f"{vnd(o['total'] or 0)} · lí do: {reason}")
    return jsonify({"success": True})


@bp.route('/api/manager/invoice/<int:order_id>/restore', methods=['POST'])
def api_manager_invoice_restore(order_id):
    with transaction() as cur:
        cur.execute("SELECT id, table_id, total, voided_at FROM orders WHERE id = %s FOR UPDATE", (order_id,))
        o = cur.fetchone()
        if not o:
            return fail("Không tìm thấy hoá đơn.", 404)
        if not o['voided_at']:
            return fail("Hoá đơn này chưa bị huỷ.")
        cur.execute("UPDATE orders SET voided_at = NULL, void_reason = NULL WHERE id = %s", (order_id,))
    audit('Khôi phục hoá đơn', f"#{order_id} · bàn {o['table_id']}", vnd(o['total'] or 0))
    return jsonify({"success": True})


@bp.route('/api/manager/export')
def api_manager_export():
    kind = request.args.get('kind', 'invoices')
    d_from, d_to = date_range()
    p = (d_from, d_to)
    buf = io.StringIO()
    buf.write('sep=;\r\n')                       # để Excel (cả máy cài tiếng Việt) tự chia cột
    w = SafeCsv(csv.writer(buf, delimiter=';'))

    if kind == 'invoices':
        w.writerow(['Mã HĐ', 'Ngày giờ thanh toán', 'Bàn', 'Gói buffet', 'Số khách', 'Tiền buffet đồ ăn',
                    'Tiền buffet nước', 'Gọi lẻ / combo', 'Giảm giá', 'VAT', 'Tổng thanh toán',
                    'Hình thức', 'Ưu đãi', 'Thu ngân', 'Trạng thái', 'Lí do huỷ'])
        rows = query("""
            SELECT o.id, to_char(o.paid_at, 'DD/MM/YYYY HH24:MI') AS paid, o.table_id,
                   COALESCE(pk.name, 'Chỉ gọi lẻ') AS package, o.guests, o.food_amount, o.drink_amount,
                   o.extra_amount, o.discount, o.vat_amount, o.total, o.payment_method, o.promo_note,
                   COALESCE(cs.name, '') AS cashier,
                   (o.voided_at IS NOT NULL) AS voided, o.void_reason
            FROM orders o LEFT JOIN packages pk ON pk.id = o.package_id
                          LEFT JOIN staffs cs ON cs.id = o.cashier_id
            WHERE o.status = 'CLOSED' AND o.paid_at IS NOT NULL AND o.paid_at::date BETWEEN %s AND %s
            ORDER BY o.paid_at""", p)
        methods = {'CASH': 'Tiền mặt', 'CARD': 'Thẻ', 'TRANSFER': 'Chuyển khoản'}
        pay_by_order = {}
        for pr in query("""SELECT p.order_id, p.method, p.amount::int AS amount
                           FROM order_payments p JOIN orders o ON o.id = p.order_id
                           WHERE o.paid_at::date BETWEEN %s AND %s ORDER BY p.id""", p):
            pay_by_order.setdefault(pr['order_id'], []).append(pr)
        for r in rows:
            w.writerow([r['id'], r['paid'], r['table_id'], r['package'], r['guests'], r['food_amount'] or 0,
                        r['drink_amount'] or 0, r['extra_amount'] or 0, r['discount'] or 0, r['vat_amount'] or 0,
                        r['total'] or 0, ' + '.join(
                            methods.get(x['method'], x['method']) + (' %s' % x['amount'] if len(pay_by_order[r['id']]) > 1 else '')
                            for x in pay_by_order.get(r['id'], [])),
                        r['promo_note'] or '', r['cashier'], 'Đã huỷ' if r['voided'] else 'Đã thanh toán', r['void_reason'] or ''])
    elif kind == 'dishes':
        w.writerow(['Món', 'Nhóm', 'Loại', 'Số lượng', 'Doanh thu'])
        base = f"""FROM order_items oi JOIN orders o ON o.id = oi.order_id
                   WHERE {PAID} AND o.paid_at::date BETWEEN %s AND %s AND oi.status <> 'CANCELLED'"""
        for r in query(f"""SELECT oi.name, SUM(oi.qty)::int AS qty {base} AND oi.kind = 'PACKAGE'
                           GROUP BY oi.name ORDER BY qty DESC, oi.name""", p):
            w.writerow([r['name'], '', 'Món trong buffet', r['qty'], 0])
        for r in query(f"""SELECT oi.name, COALESCE(MAX(a.category), '') AS category, SUM(oi.qty)::int AS qty,
                                  SUM(oi.qty * oi.unit_price)::bigint AS revenue
                           {base} AND oi.parent_id IS NULL AND oi.kind IN ('ALACARTE', 'COMBO')
                           GROUP BY oi.name ORDER BY revenue DESC, oi.name""".replace(
                "FROM order_items oi JOIN orders o ON o.id = oi.order_id",
                "FROM order_items oi JOIN orders o ON o.id = oi.order_id LEFT JOIN alacarte_items a ON a.name = oi.name"), p):
            w.writerow([r['name'], r['category'], 'Gọi lẻ / combo', r['qty'], r['revenue']])
    else:
        return fail("Loại báo cáo không hợp lệ.")

    audit('Xuất báo cáo', 'Hoá đơn' if kind == 'invoices' else 'Thống kê món', f"{d_from} → {d_to}")
    return Response('﻿' + buf.getvalue(), mimetype='text/csv; charset=utf-8',
                    headers={"Content-Disposition": f"attachment; filename=gyusachi_{kind}_{d_from}_{d_to}.csv"})
