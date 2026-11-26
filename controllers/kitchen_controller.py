"""Người phụ trách: Nguyên An
Mô tả: Bếp: danh sách món theo trạm và đổi trạng thái NEW, DOING, DONE.
"""

from flask import render_template, request, jsonify, redirect, url_for, session, Blueprint

from core.auth import manager_ok
from core.db import query, transaction
from core.helpers import fail

bp = Blueprint('kitchen', __name__)


@bp.route('/bep')
def bep():
    station_id = request.args.get('station')

    station = query(
        'SELECT id, name, icon, description AS "desc" FROM stations WHERE id = %s',
        (station_id,), one=True
    )

    if not station:
        return redirect(url_for('auth.home'))

    return render_template('kitchen/bep.html', station=dict(station))


@bp.route('/api/kitchen/<station_id>')
def api_kitchen(station_id):
    """Các món của 1 trạm: chờ làm, đang làm, và đã xong trong 30 phút gần nhất."""
    if session.get('station') != station_id and not manager_ok():
        return fail("Chưa đăng nhập bếp, hãy nhập PIN trạm.", 401)
    rows = query("""
        SELECT oi.id, o.table_id AS "table",
               CASE WHEN oi.parent_id IS NULL THEN oi.name
                    ELSE oi.name || ' (' || p.name || ')' END AS name,
               oi.qty, oi.status, oi.note,
               to_char(oi.created_at, 'HH24:MI') AS time
        FROM order_items oi
        JOIN orders o ON o.id = oi.order_id
        LEFT JOIN order_items p ON p.id = oi.parent_id
        WHERE oi.station_id = %s
          AND o.status = 'OPEN'
          AND oi.status IN ('NEW', 'DOING', 'DONE')
          AND (oi.status <> 'DONE' OR oi.updated_at > NOW() - INTERVAL '30 minutes')
        ORDER BY oi.created_at, oi.id
    """, (station_id,))
    return jsonify({"items": [dict(r) for r in rows]})


@bp.route('/api/kitchen/item/<int:item_id>/status', methods=['POST'])
def api_kitchen_status(item_id):
    """Bếp đổi trạng thái: NEW -> DOING -> DONE (không đi lùi)."""
    data = request.get_json() or {}
    new_status = data.get('status')
    station_id = data.get('station_id')
    if session.get('station') != station_id and not manager_ok():
        return fail("Chưa đăng nhập bếp, hãy nhập PIN trạm.", 401)

    flow = {'DOING': 'NEW', 'DONE': 'DOING'}      # trạng thái mới -> trạng thái trước đó bắt buộc
    if new_status not in flow:
        return fail("Trạng thái không hợp lệ.")

    with transaction() as cur:
        cur.execute("SELECT order_id FROM order_items WHERE id = %s", (item_id,))
        it0 = cur.fetchone()
        if it0:
            cur.execute("SELECT status FROM orders WHERE id = %s FOR UPDATE", (it0['order_id'],))   # cùng thứ tự khoá với thanh toán/huỷ món
            od0 = cur.fetchone()
            if not od0 or od0['status'] != 'OPEN':
                return fail("Đơn này đã đóng, không đổi trạng thái món được nữa.", 409)
        cur.execute("""
            UPDATE order_items SET status = %s, updated_at = NOW()
            WHERE id = %s AND station_id = %s AND status = %s
              AND order_id IN (SELECT id FROM orders WHERE status = 'OPEN')
            RETURNING id
        """, (new_status, item_id, station_id, flow[new_status]))
        done = cur.fetchone()

    if not done:
        return fail("Món đã đổi trạng thái hoặc bị huỷ, hãy tải lại.", 409)
    return jsonify({"success": True})
