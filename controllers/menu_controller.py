"""Người phụ trách: Nguyên An
Mô tả: Quản lí thực đơn: món buffet, món gọi lẻ, combo (thêm, sửa, ẩn/hiện, xoá).
"""

from flask import request, jsonify, Blueprint

from core.audit import audit
from core.db import query, transaction
from core.helpers import CATEGORY_ORDER, OrderError, clean_name, fail, vnd

bp = Blueprint('menu', __name__)


@bp.route('/api/manager/menu')
def api_manager_menu():
    ala = query("""
        SELECT a.id, a.name, a.category, a.station_code AS station, a.price::int AS price, a.is_active,
               EXISTS (SELECT 1 FROM combo_details c WHERE c.combo_id = a.id) AS is_combo
        FROM alacarte_items a ORDER BY a.id""")
    buffet = query("""
        SELECT m.id, m.name, m.category, m.station_id AS station, m.is_active, MIN(p.price)::int AS from_price
        FROM menu_items m
        LEFT JOIN package_items pi ON pi.menu_item_id = m.id
        LEFT JOIN packages p ON p.id = pi.package_id
        GROUP BY m.id ORDER BY m.id""")
    stations = query("SELECT id, name FROM stations ORDER BY id")
    packages = query("SELECT id, name, price FROM packages ORDER BY price")
    return jsonify({"alacarte": [dict(r) for r in ala], "buffet": [dict(r) for r in buffet],
                    "category_order": CATEGORY_ORDER,
                    "stations": [dict(r) for r in stations], "packages": [dict(r) for r in packages]})


@bp.route('/api/manager/alacarte/new', methods=['POST'])
def api_manager_alacarte_new():
    """Thêm món gọi lẻ / nước mới."""
    data = request.get_json() or {}
    try:
        name = clean_name(data.get('name'), 255)
        category = clean_name(data.get('category'), 100)
        try:
            price = int(data.get('price'))
        except (TypeError, ValueError):
            raise OrderError("Giá không hợp lệ.")
        if not 0 <= price <= 10_000_000:
            raise OrderError("Giá phải từ 0 đến 10.000.000đ.")

        with transaction() as cur:
            cur.execute("SELECT id FROM stations WHERE id = %s", (data.get('station_code'),))
            if not cur.fetchone():
                raise OrderError("Hãy chọn trạm bếp.")
            cur.execute("SELECT id FROM alacarte_items WHERE LOWER(name) = LOWER(%s)", (name,))
            if cur.fetchone():
                raise OrderError("Đã có món tên này trong thực đơn gọi lẻ.")
            cur.execute("""INSERT INTO alacarte_items (name, category, station_code, price)
                           VALUES (%s, %s, %s, %s) RETURNING id""",
                        (name, category, data.get('station_code'), price))
            new_id = cur.fetchone()['id']
    except OrderError as e:
        return fail(str(e))
    return jsonify({"success": True, "id": new_id})


@bp.route('/api/manager/menu-item/new', methods=['POST'])
def api_manager_menu_item_new():
    """Thêm món buffet mới và gắn vào các gói được chọn."""
    data = request.get_json() or {}
    try:
        name = clean_name(data.get('name'), 150)
        category = clean_name(data.get('category'), 100)
        raw = data.get('package_ids') or []
        try:
            package_ids = sorted({int(x) for x in raw})
        except (TypeError, ValueError):
            raise OrderError("Gói buffet không hợp lệ.")
        if not package_ids:
            raise OrderError("Hãy chọn ít nhất một gói buffet.")

        with transaction() as cur:
            cur.execute("SELECT id FROM stations WHERE id = %s", (data.get('station_id'),))
            if not cur.fetchone():
                raise OrderError("Hãy chọn trạm bếp.")
            cur.execute("SELECT id FROM packages WHERE id = ANY(%s)", (package_ids,))
            if len(cur.fetchall()) != len(package_ids):
                raise OrderError("Có gói buffet không tồn tại.")
            cur.execute("SELECT id FROM menu_items WHERE LOWER(name) = LOWER(%s)", (name,))
            if cur.fetchone():
                raise OrderError("Đã có món buffet tên này.")
            cur.execute("""INSERT INTO menu_items (name, category, station_id)
                           VALUES (%s, %s, %s) RETURNING id""",
                        (name, category, data.get('station_id')))
            new_id = cur.fetchone()['id']
            for pid in package_ids:
                cur.execute("INSERT INTO package_items (package_id, menu_item_id) VALUES (%s, %s)",
                            (pid, new_id))
    except OrderError as e:
        return fail(str(e))
    return jsonify({"success": True, "id": new_id})


@bp.route('/api/manager/alacarte/<int:item_id>', methods=['POST'])
def api_manager_alacarte(item_id):
    data = request.get_json() or {}
    changes = []
    try:
        with transaction() as cur:
            cur.execute("""SELECT a.id, a.name, a.category, a.station_code, a.price::int AS price, a.is_active,
                                  EXISTS (SELECT 1 FROM combo_details c WHERE c.combo_id = a.id) AS is_combo
                           FROM alacarte_items a WHERE a.id = %s FOR UPDATE""", (item_id,))
            old = cur.fetchone()
            if not old:
                raise OrderError("Không tìm thấy món.")
            sets, params = [], []

            if 'name' in data:
                name = clean_name(data['name'], 255)
                if name != old['name']:
                    cur.execute("SELECT 1 FROM alacarte_items WHERE LOWER(name) = LOWER(%s) AND id <> %s", (name, item_id))
                    if cur.fetchone():
                        raise OrderError("Đã có món gọi lẻ tên này.")
                    sets.append("name = %s"); params.append(name)
                    changes.append(f"tên “{old['name']}” → “{name}”")

            if 'category' in data:
                cat = clean_name(data['category'], 100)
                if cat != old['category']:
                    sets.append("category = %s"); params.append(cat)
                    changes.append(f"nhóm {old['category']} → {cat}")

            if 'station_code' in data and data['station_code'] != old['station_code']:
                if old['is_combo']:
                    raise OrderError("Combo gồm nhiều món con nên không đổi trạm bếp được.")
                cur.execute("SELECT id FROM stations WHERE id = %s", (data['station_code'],))
                if not cur.fetchone():
                    raise OrderError("Trạm bếp không hợp lệ.")
                sets.append("station_code = %s"); params.append(data['station_code'])
                changes.append(f"trạm {old['station_code']} → {data['station_code']}")

            if 'price' in data:
                try:
                    price = int(data['price'])
                except (TypeError, ValueError):
                    raise OrderError("Giá không hợp lệ.")
                if not 0 <= price <= 10_000_000:
                    raise OrderError("Giá phải từ 0 đến 10.000.000đ.")
                if price != old['price']:
                    sets.append("price = %s"); params.append(price)
                    changes.append(f"giá {vnd(old['price'])} → {vnd(price)}")

            if 'is_active' in data and bool(data['is_active']) != old['is_active']:
                sets.append("is_active = %s"); params.append(bool(data['is_active']))
                changes.append("bán lại" if data['is_active'] else "tắt (hết hàng)")

            if not sets:
                if changes or any(k in data for k in ('name', 'category', 'station_code', 'price', 'is_active')):
                    return jsonify({"success": True})       # không có gì thay đổi
                raise OrderError("Không có gì để cập nhật.")
            cur.execute(f"UPDATE alacarte_items SET {', '.join(sets)} WHERE id = %s", (*params, item_id))
    except OrderError as e:
        return fail(str(e))
    audit('Sửa món gọi lẻ', old['name'], '; '.join(changes))
    return jsonify({"success": True})


@bp.route('/api/manager/alacarte/<int:item_id>/delete', methods=['POST'])
def api_manager_alacarte_delete(item_id):
    with transaction() as cur:
        cur.execute("SELECT id, name FROM alacarte_items WHERE id = %s FOR UPDATE", (item_id,))
        a = cur.fetchone()
        if not a:
            return fail("Không tìm thấy món.", 404)
        cur.execute("SELECT 1 FROM order_items WHERE name = %s LIMIT 1", (a['name'],))
        if cur.fetchone():
            return fail("Món này đã có lịch sử gọi nên không xoá được (xoá sẽ làm sai báo cáo). Hãy bấm TẮT để ẩn món.")
        cur.execute("DELETE FROM alacarte_items WHERE id = %s", (item_id,))      # combo_details tự xoá theo
    audit('Xoá món gọi lẻ', a['name'])
    return jsonify({"success": True})


@bp.route('/api/manager/menu-item/<int:item_id>', methods=['POST'])
def api_manager_menu_item(item_id):
    data = request.get_json() or {}
    changes = []
    try:
        with transaction() as cur:
            cur.execute("SELECT id, name, category, station_id, is_active FROM menu_items WHERE id = %s FOR UPDATE",
                        (item_id,))
            old = cur.fetchone()
            if not old:
                raise OrderError("Không tìm thấy món.")
            sets, params = [], []

            if 'name' in data:
                name = clean_name(data['name'], 150)
                if name != old['name']:
                    cur.execute("SELECT 1 FROM menu_items WHERE LOWER(name) = LOWER(%s) AND id <> %s", (name, item_id))
                    if cur.fetchone():
                        raise OrderError("Đã có món buffet tên này.")
                    sets.append("name = %s"); params.append(name)
                    changes.append(f"tên “{old['name']}” → “{name}”")

            if 'category' in data:
                cat = clean_name(data['category'], 100)
                if cat != old['category']:
                    sets.append("category = %s"); params.append(cat)
                    changes.append(f"nhóm {old['category']} → {cat}")

            if 'station_id' in data and data['station_id'] != old['station_id']:
                cur.execute("SELECT id FROM stations WHERE id = %s", (data['station_id'],))
                if not cur.fetchone():
                    raise OrderError("Trạm bếp không hợp lệ.")
                sets.append("station_id = %s"); params.append(data['station_id'])
                changes.append(f"trạm {old['station_id']} → {data['station_id']}")

            if 'is_active' in data and bool(data['is_active']) != old['is_active']:
                sets.append("is_active = %s"); params.append(bool(data['is_active']))
                changes.append("bán lại" if data['is_active'] else "tắt (hết nguyên liệu)")

            if not sets:
                if any(k in data for k in ('name', 'category', 'station_id', 'is_active')):
                    return jsonify({"success": True})
                raise OrderError("Không có gì để cập nhật.")
            cur.execute(f"UPDATE menu_items SET {', '.join(sets)} WHERE id = %s", (*params, item_id))
    except OrderError as e:
        return fail(str(e))
    audit('Sửa món buffet', old['name'], '; '.join(changes))
    return jsonify({"success": True})


@bp.route('/api/manager/menu-item/<int:item_id>/delete', methods=['POST'])
def api_manager_menu_item_delete(item_id):
    with transaction() as cur:
        cur.execute("SELECT id, name FROM menu_items WHERE id = %s FOR UPDATE", (item_id,))
        m = cur.fetchone()
        if not m:
            return fail("Không tìm thấy món.", 404)
        cur.execute("SELECT 1 FROM order_items WHERE menu_item_id = %s LIMIT 1", (item_id,))
        if cur.fetchone():
            return fail("Món này đã có lịch sử gọi nên không xoá được (xoá sẽ làm sai báo cáo). Hãy bấm TẮT để ẩn món.")
        cur.execute("DELETE FROM menu_items WHERE id = %s", (item_id,))          # package_items tự xoá theo
    audit('Xoá món buffet', m['name'])
    return jsonify({"success": True})
