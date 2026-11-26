"""Người phụ trách: Mai Linh
Mô tả: Trang chủ, đăng nhập bằng PIN của nhân viên/trạm bếp và đăng nhập của quản lí.
"""

from flask import render_template, request, jsonify, session, Blueprint

from core.auth import MGR_ROLES, current_mgr, lock_message, pin_check, pin_failed, pin_locked, pin_ok
from core.db import query
from core.helpers import fail
from models.staff_model import get_staffs, get_stations
from models.table_model import get_tables

bp = Blueprint('auth', __name__)


@bp.route('/')
def home():
    return render_template(
        'home/index.html',
        staffs=get_staffs(),
        stations=get_stations(),
        tables=get_tables()
    )


@bp.route('/api/verify-pin', methods=['POST'])
def verify_pin():

    data = request.get_json() or {}
    code = str(data.get('id', '')).strip()
    entered_pin = str(data.get('pin', '')).strip()

    left = pin_locked('staff')
    if left:
        return jsonify({"success": False, "message": lock_message(left)}), 429

    try:
        staff = query("SELECT id, name, pin FROM staffs WHERE id = %s AND is_active AND role NOT IN ('Chủ', 'Admin')", (code,), one=True)
        if staff and not pin_check(staff['pin'], entered_pin):
            staff = None
        station = query("SELECT id, name, pin FROM stations WHERE id = %s", (code,), one=True)
        if station and not pin_check(station['pin'], entered_pin):
            station = None
    except Exception as e:
        print("Lỗi database:", e)
        return jsonify({
            "success": False,
            "message": "Không kết nối được cơ sở dữ liệu!"
        })

    if staff or station:
        pin_ok('staff')
    else:
        pin_failed('staff')

    if staff:
        session.permanent = True
        session.pop('station', None)                # máy này giờ là máy phục vụ, không còn là máy bếp
        session['staff'] = staff['id']              # nhớ nhân viên đã nhập đúng PIN (để phân biệt với khách quét QR)
        return jsonify({
            "success": True,
            "message": f"Chào mừng {staff['name']} vào ca!",
            "redirect": f"/phucvu?staff={staff['id']}"
        })

    if station:
        session.permanent = True
        for k_ in ('staff', 'manager', 'manager_id', 'cashier', 'cashier_id'):
            session.pop(k_, None)                   # máy bếp không giữ quyền phục vụ/quản lí/thu ngân
        session['station'] = station['id']
        return jsonify({
            "success": True,
            "message": f"Chào mừng đến {station['name']}!",
            "redirect": f"/bep?station={station['id']}"
        })

    return jsonify({
        "success": False,
        "message": "Mã PIN không đúng!"
    })


@bp.route('/api/manager/login', methods=['POST'])
def api_manager_login():
    """Quản lí đăng nhập bằng PIN 4 số của nhân viên có chức vụ 'Quản lí' (bảng staffs)."""
    pin = str((request.get_json() or {}).get('pin', '')).strip()
    left = pin_locked('manager')
    if left:
        return fail(lock_message(left), 429)
    mgr = next((m for m in query("SELECT id, name, role, pin FROM staffs WHERE is_active AND role = ANY(%s)",
                                 (list(MGR_ROLES),)) if pin_check(m['pin'], pin)), None)
    if not mgr:
        pin_failed('manager')
        return fail("Mã PIN không đúng.", 401)
    pin_ok('manager')
    session.permanent = True
    session.pop('station', None)
    session['manager'] = True
    session['manager_id'] = mgr['id']
    return jsonify({"success": True, "name": mgr['name'], "role": mgr['role']})


@bp.route('/api/manager/me')
def api_manager_me():
    m = current_mgr()
    return jsonify({"logged_in": bool(m), "role": m['role'] if m else None, "name": m['name'] if m else None})


@bp.route('/api/manager/logout', methods=['POST'])
def api_manager_logout():
    session.pop('manager', None)
    session.pop('manager_id', None)
    return jsonify({"success": True})
