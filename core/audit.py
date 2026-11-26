"""Người phụ trách: Mai Linh
Mô tả: Nhật ký thao tác của quản lí: hàm audit() và tự ghi nhật ký sau các thao tác quản lí thành công (không bao giờ ghi PIN/mật khẩu).
"""

import re

from flask import request, g

from core.auth import current_mgr
from core.db import transaction


def audit(action, target='', detail='', actor=None):
    """Ghi nhật ký. Lỗi ghi nhật ký (VD chưa chạy file 18) không bao giờ làm hỏng thao tác chính."""
    g.audited = True
    if actor is None:
        m = current_mgr()
        actor = ("%s (%s)" % (m['name'], m['role'])) if m else 'Quản lí'
    try:
        with transaction() as cur:
            cur.execute("INSERT INTO audit_log (actor, action, target, detail) VALUES (%s, %s, %s, %s)",
                        (str(actor)[:50], str(action)[:100], str(target)[:200], str(detail)[:500]))
    except Exception:
        pass


AUDIT_ROUTES = [
    (r'^/api/manager/system/cleanup$',          'Dọn dữ liệu kẹt'),
    (r'^/api/manager/system/reset-pin$',        'Đặt lại PIN (admin)'),
    (r'^/api/manager/staff/new$',               'Thêm nhân viên'),
    (r'^/api/manager/staff/[^/]+/delete$',      'Xoá nhân viên'),
    (r'^/api/manager/staff/[^/]+$',             'Sửa nhân viên'),
    (r'^/api/manager/station/[^/]+/pin$',       'Đổi PIN trạm bếp'),
    (r'^/api/manager/password$',                'Đổi mật khẩu'),
    (r'^/api/manager/table/new$',               'Thêm bàn'),
    (r'^/api/manager/table/[^/]+/delete$',      'Xoá bàn'),
    (r'^/api/manager/table/[^/]+$',             'Sửa bàn'),
    (r'^/api/manager/package/\d+$',             'Sửa gói buffet'),
    (r'^/api/manager/alacarte/new$',            'Thêm món gọi lẻ'),
    (r'^/api/manager/menu-item/new$',           'Thêm món buffet'),
]


AUDIT_FIELDS = {'name': 'tên', 'role': 'chức vụ', 'is_active': 'trạng thái', 'price': 'giá', 'days': 'ngày áp dụng',
                'capacity': 'số chỗ', 'min_capacity': 'số chỗ tối thiểu', 'floor': 'tầng', 'type': 'loại',
                'category': 'nhóm', 'avatar': 'ảnh', 'customer_name': 'khách', 'guests': 'số khách',
                'table_id': 'bàn', 'date': 'ngày', 'time': 'giờ', 'id': 'mã', 'package_ids': 'gói',
                'station_code': 'trạm', 'station_id': 'trạm', 'phone': 'SĐT', 'note': 'ghi chú'}


AUDIT_SECRET = {'pin', 'password', 'current', 'new'}


def audit_manager_changes(resp):
    """Tự ghi nhật ký cho các thao tác quản lí đã thành công mà không có đoạn ghi riêng. Không bao giờ ghi PIN/mật khẩu."""
    try:
        if (request.method != 'POST' or not request.path.startswith('/api/manager/') or getattr(g, 'audited', False)
                or resp.status_code != 200 or not resp.is_json or not (resp.get_json() or {}).get('success')):
            return resp
        for pattern, label in AUDIT_ROUTES:
            if re.match(pattern, request.path):
                body = request.get_json(silent=True) or {}
                parts = []
                for k, v in body.items():
                    if k in AUDIT_SECRET or k == 'which':
                        continue
                    if isinstance(v, bool):
                        v = 'bật' if v else 'tắt'
                    parts.append(f"{AUDIT_FIELDS.get(k, k)}: {v}")
                if any(k in body for k in AUDIT_SECRET - {'password'}) and 'password' not in request.path:
                    parts.append(('đặt mã PIN' if request.path.endswith('/new') else 'đổi mã PIN') if 'pin' in body else '')
                if request.path.endswith('/password'):
                    parts = ['mật khẩu ' + ('thu ngân' if body.get('which') == 'cashier' else 'quản lí')]
                target = 'Mật khẩu' if request.path.endswith('/password') else body.get('name') or body.get('customer_name') or request.path.rstrip('/').split('/')[-2 if request.path.endswith(('/delete', '/pin')) else -1]
                audit(label, target, ', '.join(x for x in parts if x))
                break
    except Exception:
        pass
    return resp


def register_audit(app):
    """Gắn bước ghi nhật ký chạy sau mỗi yêu cầu."""
    app.after_request(audit_manager_changes)
