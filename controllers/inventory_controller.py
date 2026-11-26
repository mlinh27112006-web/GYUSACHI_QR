"""Người phụ trách: Nguyên An
Mô tả: Kho phục vụ của quản lí: vật tư, nhập/kiểm kê, sổ kho, chốt ngày.
"""

from flask import request, jsonify, Blueprint

from core.audit import audit
from core.db import query, transaction
from core.helpers import OrderError, clean_name, fail, num, parse_day, vn_now
from models.inventory_model import PV_FIELDS, pv_auto_fields, pv_row
from models.report_model import PAID

bp = Blueprint('inventory', __name__)


@bp.route('/api/manager/inventory/moves')
def api_manager_inventory_moves():
    """Sổ kho phục vụ (bảng lich_su_kho)."""
    wh = request.args.get('wh', '')
    q = (request.args.get('q') or '').strip()[:100]
    like = f"%{q}%"
    try:
        limit = max(1, min(int(request.args.get('limit') or 200), 500))
    except ValueError:
        limit = 200
    out = []
    if True:
        lab = {'NHAP': ('IN', 'Nhập kho'), 'XUAT_TU_DONG': ('AUTO', 'Tự trừ'), 'KIEM_KE': ('ADJUST', 'Kiểm kê')}
        for r in query("""
            SELECT l.created_at, to_char(l.created_at, 'DD/MM/YYYY HH24:MI') AS at, k.ten_vt AS name, k.dvt AS unit,
                   l.loai, l.so_luong AS qty, l.ghi_chu AS note
            FROM lich_su_kho l JOIN kho_phuc_vu k ON k.ma_vt = l.ma_vt
            WHERE %s = '' OR k.ten_vt ILIKE %s OR l.ghi_chu ILIKE %s OR l.ma_vt ILIKE %s
            ORDER BY l.id DESC LIMIT %s""", (q, like, like, like, limit)):
            d = dict(r); d['kind'], d['label'] = lab.get(d['loai'], (d['loai'], d['loai'])); del d['loai']
            d['warehouse'] = 'PHUCVU'; d['qty'] = float(d['qty']); d['balance_after'] = None; out.append(d)
    out.sort(key=lambda x: x['created_at'], reverse=True)
    out = out[:limit]
    for d in out:
        d['created_at'] = None
    return jsonify({"moves": out})


@bp.route('/api/manager/pv')
def api_manager_pv():
    groups = query("SELECT ma_nhom, ten_nhom FROM nhom_hang ORDER BY ma_nhom")
    rows = query(f"""SELECT {PV_FIELDS} FROM kho_phuc_vu k JOIN nhom_hang n ON n.ma_nhom = k.ma_nhom
                     ORDER BY k.ma_nhom, k.ma_vt""")
    items = [pv_row(r) for r in rows]
    act = [i for i in items if i['dang_dung']]
    return jsonify({"groups": [dict(g_) for g_ in groups], "items": items, "summary": {
        "count": len(act), "low": sum(1 for i in act if i['low']), "out": sum(1 for i in act if i['out']),
        "auto": sum(1 for i in act if i['ma_update'] == 1)}})


@bp.route('/api/manager/pv/new', methods=['POST'])
def api_manager_pv_new():
    data = request.get_json() or {}
    try:
        nhom = str(data.get('ma_nhom') or '')
        name = clean_name(data.get('ten_vt'), 150)
        dvt = clean_name(data.get('dvt'), 20)
        sl = num(data.get('so_luong', 0), "Số lượng tồn")
        mn = num(data.get('ton_toi_thieu', 0), "Mức cảnh báo")
        mu, kieu, dm = pv_auto_fields(data)
        ghi = ' '.join(str(data.get('ghi_chu') or '').split())[:300] or None
        with transaction() as cur:
            cur.execute("SELECT 1 FROM nhom_hang WHERE ma_nhom = %s", (nhom,))
            if not cur.fetchone():
                raise OrderError("Hãy chọn nhóm hàng.")
            cur.execute("SELECT 1 FROM kho_phuc_vu WHERE lower(ten_vt) = lower(%s)", (name,))
            if cur.fetchone():
                raise OrderError("Đã có vật tư cùng tên.")
            cur.execute("SELECT COALESCE(MAX(substring(ma_vt from '[0-9]+$')::int), 0) + 1 AS n FROM kho_phuc_vu WHERE ma_nhom = %s", (nhom,))
            ma = f"{nhom}-{cur.fetchone()['n']:03d}"
            cur.execute("""INSERT INTO kho_phuc_vu (ma_vt, ma_nhom, ten_vt, dvt, so_luong, ton_toi_thieu, ma_update, kieu_tru, dinh_muc, ghi_chu)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""", (ma, nhom, name, dvt, sl, mn, mu, kieu, dm, ghi))
            if sl > 0:
                cur.execute("INSERT INTO lich_su_kho (ma_vt, loai, so_luong, ghi_chu) VALUES (%s, 'NHAP', %s, 'Tồn đầu kỳ')", (ma, sl))
        audit('Thêm vật tư kho phục vụ', name, f"mã {ma}, tồn {sl} {dvt}")
    except (OrderError, TypeError, ValueError) as e:
        return fail(str(e) if isinstance(e, OrderError) else "Dữ liệu không hợp lệ.")
    return jsonify({"success": True, "ma_vt": ma})


@bp.route('/api/manager/pv/<ma_vt>', methods=['POST'])
def api_manager_pv_edit(ma_vt):
    data = request.get_json() or {}
    try:
        with transaction() as cur:
            cur.execute("SELECT ma_vt, ten_vt, ma_update FROM kho_phuc_vu WHERE ma_vt = %s FOR UPDATE", (ma_vt,))
            it = cur.fetchone()
            if not it:
                raise OrderError("Không tìm thấy vật tư.")
            sets, params = [], []
            if 'ten_vt' in data:
                nm = clean_name(data['ten_vt'], 150)
                cur.execute("SELECT 1 FROM kho_phuc_vu WHERE lower(ten_vt) = lower(%s) AND ma_vt <> %s", (nm, ma_vt))
                if cur.fetchone():
                    raise OrderError("Đã có vật tư cùng tên.")
                sets.append("ten_vt = %s"); params.append(nm)
            if 'dvt' in data:
                sets.append("dvt = %s"); params.append(clean_name(data['dvt'], 20))
            if 'ton_toi_thieu' in data:
                sets.append("ton_toi_thieu = %s"); params.append(num(data['ton_toi_thieu'], "Mức cảnh báo"))
            if 'ghi_chu' in data:
                sets.append("ghi_chu = %s"); params.append(' '.join(str(data['ghi_chu'] or '').split())[:300] or None)
            if 'dang_dung' in data:
                sets.append("dang_dung = %s"); params.append(bool(data['dang_dung']))
            if 'ma_update' in data:
                mu, kieu, dm = pv_auto_fields(data)
                sets += ["ma_update = %s", "kieu_tru = %s", "dinh_muc = %s"]; params += [mu, kieu, dm]
            if not sets:
                raise OrderError("Không có gì để cập nhật.")
            sets.append("updated_at = NOW()")
            cur.execute(f"UPDATE kho_phuc_vu SET {', '.join(sets)} WHERE ma_vt = %s", (*params, ma_vt))
        audit('Sửa vật tư kho phục vụ', it['ten_vt'], ', '.join(k for k in data if k in
              ('ten_vt', 'dvt', 'ton_toi_thieu', 'ghi_chu', 'dang_dung', 'ma_update', 'kieu_tru', 'dinh_muc')))
    except (OrderError, TypeError, ValueError) as e:
        return fail(str(e) if isinstance(e, OrderError) else "Dữ liệu không hợp lệ.")
    return jsonify({"success": True})


@bp.route('/api/manager/pv/<ma_vt>/delete', methods=['POST'])
def api_manager_pv_delete(ma_vt):
    with transaction() as cur:
        cur.execute("SELECT ten_vt FROM kho_phuc_vu WHERE ma_vt = %s FOR UPDATE", (ma_vt,))
        it = cur.fetchone()
        if not it:
            return fail("Không tìm thấy vật tư.", 404)
        cur.execute("SELECT 1 FROM lich_su_kho WHERE ma_vt = %s AND loai <> 'NHAP' LIMIT 1", (ma_vt,))
        if cur.fetchone():
            return fail("Vật tư này đã có lịch sử kiểm kê / tự trừ nên giữ lại, hãy bấm TẮT để ẩn.")
        cur.execute("DELETE FROM lich_su_kho WHERE ma_vt = %s", (ma_vt,))
        cur.execute("DELETE FROM kho_phuc_vu WHERE ma_vt = %s", (ma_vt,))
    audit('Xoá vật tư kho phục vụ', it['ten_vt'])
    return jsonify({"success": True})


@bp.route('/api/manager/pv/<ma_vt>/move', methods=['POST'])
def api_manager_pv_move(ma_vt):
    """kind = IN (nhập thêm, gọi hàm nhap_kho) | ADJUST (kiểm kê: đặt lại số thực tế, gọi hàm kiem_ke)."""
    data = request.get_json() or {}
    try:
        kind = data.get('kind')
        if kind not in ('IN', 'ADJUST'):
            raise OrderError("Loại phiếu không hợp lệ.")
        qty = num(data.get('qty'), "Số lượng", minimum=0)
        if kind == 'IN' and qty <= 0:
            raise OrderError("Số lượng nhập phải lớn hơn 0.")
        note = ' '.join(str(data.get('note') or '').split())[:200] or None
        with transaction() as cur:
            cur.execute("SELECT ten_vt, dvt FROM kho_phuc_vu WHERE ma_vt = %s FOR UPDATE", (ma_vt,))
            it = cur.fetchone()
            if not it:
                raise OrderError("Không tìm thấy vật tư.")
            if kind == 'IN':
                cur.execute("SELECT nhap_kho(%s, %s, %s)", (ma_vt, qty, note))
            else:
                cur.execute("SELECT kiem_ke(%s, %s, %s)", (ma_vt, qty, note))
            cur.execute("SELECT so_luong FROM kho_phuc_vu WHERE ma_vt = %s", (ma_vt,))
            new = float(cur.fetchone()['so_luong'])
        audit('Nhập kho phục vụ' if kind == 'IN' else 'Kiểm kê kho phục vụ', it['ten_vt'],
              f"{'+' if kind == 'IN' else '→ '}{qty:g} {it['dvt']}, tồn {new:g}" + (f" ({note})" if note else ''))
    except OrderError as e:
        return fail(str(e))
    return jsonify({"success": True, "stock": new})


@bp.route('/api/manager/pv/day')
def api_manager_pv_day():
    """Thông tin chốt ngày: số khách đã lưu, số khách gợi ý (từ hoá đơn đã thanh toán), ngày đó đã chốt chưa."""
    try:
        day = parse_day(request.args.get('date') or vn_now().date().isoformat())
    except OrderError as e:
        return fail(str(e))
    saved = query("SELECT so_khach FROM so_khach_ngay WHERE ngay = %s", (day,), one=True)
    sug = query(f"SELECT COALESCE(SUM(o.guests), 0)::int AS n FROM orders o WHERE {PAID} AND o.paid_at::date = %s", (day,), one=True)['n']
    done = query("SELECT COUNT(*)::int AS n FROM lich_su_kho WHERE ngay = %s AND loai = 'XUAT_TU_DONG'", (day,), one=True)['n']
    auto = query("SELECT COUNT(*)::int AS n FROM kho_phuc_vu WHERE dang_dung AND ma_update = 1 AND dinh_muc > 0", one=True)['n']
    return jsonify({"date": day.isoformat(), "saved": saved['so_khach'] if saved else None,
                    "suggest": sug, "done": done, "auto": auto})


@bp.route('/api/manager/pv/chot', methods=['POST'])
def api_manager_pv_chot():
    """Nhập số khách rồi chốt ngày: tự trừ các vật tư ma_update = 1. Chốt lại cùng ngày không bị trừ đôi."""
    data = request.get_json() or {}
    try:
        day = parse_day(data.get('date'))
        if day > vn_now().date():
            raise OrderError("Chưa chốt được ngày trong tương lai.")
        khach = int(num(data.get('so_khach'), "Số khách", minimum=0, maximum=100000))
        with transaction() as cur:
            cur.execute("""INSERT INTO so_khach_ngay (ngay, so_khach) VALUES (%s, %s)
                           ON CONFLICT (ngay) DO UPDATE SET so_khach = EXCLUDED.so_khach""", (day, khach))
            cur.execute("SELECT chot_ngay(%s) AS n", (day,))
            n = cur.fetchone()['n']
        audit('Chốt ngày kho phục vụ', day.strftime('%d/%m/%Y'), f"{khach} khách, trừ {n} vật tư")
    except OrderError as e:
        return fail(str(e))
    return jsonify({"success": True, "trimmed": n})
