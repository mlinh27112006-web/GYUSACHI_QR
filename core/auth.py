"""Người phụ trách: Mai Linh
Mô tả: Xác thực và phân quyền: chặn dò PIN, băm/kiểm tra PIN, tài khoản quản lí đang đăng nhập, mã QR từng bàn (HMAC), các bước kiểm tra quyền trước mỗi yêu cầu.
"""

import hashlib
import hmac
import re
import threading
import time

from flask import request, session, g, current_app
from werkzeug.security import generate_password_hash, check_password_hash

from core.db import query
from core.helpers import OrderError, fail


# ---- Chặn dò mã PIN: sai 5 lần liên tiếp thì khoá 5 phút (theo địa chỉ IP + loại đăng nhập) ----
_FAILS = {}


_FAILS_LOCK = threading.Lock()


MAX_PIN_FAILS = 5


PIN_LOCK_SECONDS = 300


def _client_ip():
    fwd = request.headers.get('X-Forwarded-For', '')          # Render đặt IP thật của khách ở đây
    return (fwd.split(',')[0].strip() if fwd else request.remote_addr) or '?'


def pin_locked(kind):
    """Trả số giây còn bị khoá (0 = không khoá)."""
    k = (kind, _client_ip())
    with _FAILS_LOCK:
        rec = _FAILS.get(k)
        if rec and rec['until'] > time.time():
            return int(rec['until'] - time.time()) + 1
    return 0


def pin_failed(kind):
    k = (kind, _client_ip())
    with _FAILS_LOCK:
        rec = _FAILS.setdefault(k, {'n': 0, 'until': 0})
        if rec['until'] and rec['until'] <= time.time():
            rec['n'], rec['until'] = 0, 0                     # hết thời gian khoá -> đếm lại
        rec['n'] += 1
        if rec['n'] >= MAX_PIN_FAILS:
            rec['until'] = time.time() + PIN_LOCK_SECONDS
            rec['n'] = 0


def pin_ok(kind):
    with _FAILS_LOCK:
        _FAILS.pop((kind, _client_ip()), None)


def lock_message(secs):
    return f"Nhập sai quá nhiều lần. Vui lòng thử lại sau {(secs + 59) // 60} phút."


# ---------- Mã xác thực QR của từng bàn ----------
# Mỗi bàn có một mã bí mật riêng (HMAC từ SECRET_KEY + mã bàn) nằm trong link của mã QR (?k=...).
# Khách chỉ làm việc được với đúng bàn có mã khớp; đổi mã bàn trong link/yêu cầu sẽ không đủ.
# Đổi SECRET_KEY thì mọi mã cũ mất hiệu lực (phải in lại QR).
def qr_token(table_id):
    return hmac.new(current_app.secret_key.encode('utf8'), ('qr-ban:' + str(table_id).upper()).encode('utf8'),
                    hashlib.sha256).hexdigest()[:20]


def qr_ok(table_id, token):
    return bool(token) and bool(table_id) and hmac.compare_digest(qr_token(table_id), str(token))


def table_access_ok(table_id):
    """Nhân viên/quản lí đã đăng nhập, hoặc khách có mã QR đúng của bàn đó (gửi qua header X-Table-Key)."""
    if session.get('staff') or manager_ok():
        return True
    return qr_ok(table_id, request.headers.get('X-Table-Key'))


# Ba vai dùng trang quản lí (đăng nhập bằng PIN của chính tài khoản đó trong bảng staffs):
#   Quản lí = vận hành hằng ngày | Chủ = doanh thu, giá, tài khoản | Admin = bảo trì hệ thống
MGR_ROLES = ('Quản lí', 'Chủ', 'Admin')


HIDDEN_ROLES = ('Chủ', 'Admin')          # không xuất hiện ở danh sách phục vụ / thu ngân


def current_mgr():
    """Tài khoản quản lí/chủ/admin đang đăng nhập — kiểm tra lại với database (còn hoạt động, đúng chức vụ)."""
    if hasattr(g, '_mgr'):
        return g._mgr
    row = None
    if session.get('manager') and session.get('manager_id'):
        row = query("SELECT id, name, role FROM staffs WHERE id = %s AND is_active AND role = ANY(%s)",
                    (session['manager_id'], list(MGR_ROLES)), one=True)
    if not row:
        session.pop('manager', None)
        session.pop('manager_id', None)
    g._mgr = dict(row) if row else None
    return g._mgr


def manager_ok():
    return current_mgr() is not None


def mgr_role():
    m = current_mgr()
    return m['role'] if m else None


CASHIER_OPEN_PATHS = ('/api/cashier/staff', '/api/cashier/login', '/api/cashier/me', '/api/cashier/logout')


STAFF_ONLY_API = re.compile(r'^/api/(tables|orders/open|orders/\d+/(move|merge|change-package)|service-calls(/\d+/done)?)$')


def guard_staff_api():
    """Các API của phục vụ (mở bàn, chuyển/gộp bàn, đổi gói, yêu cầu gọi nhân viên)
    chỉ dùng được khi đã nhập PIN nhân viên; khách quét QR không gọi được."""
    if not STAFF_ONLY_API.match(request.path):
        return None
    sid = session.get('staff')
    # tài khoản bị khoá/xoá sau khi đăng nhập thì phiên cũ hết hiệu lực
    if sid and not query("SELECT 1 FROM staffs WHERE id = %s AND is_active", (sid,), one=True):
        session.pop('staff', None)
    if not (session.get('staff') or manager_ok()):
        return fail("Hết phiên đăng nhập hoặc tài khoản đã bị khoá, hãy đăng nhập lại.", 401)
    return None


def guard_cashier_api():
    """Mọi API /api/cashier/* (trừ chọn người thu / đăng nhập / kiểm tra / đăng xuất) cần đã đăng nhập quầy thu ngân."""
    if request.path.startswith('/api/cashier/') and request.path not in CASHIER_OPEN_PATHS:
        cid = session.get('cashier_id')
        if not session.get('cashier') or not cid or \
                not query("SELECT 1 FROM staffs WHERE id = %s AND is_active", (cid,), one=True):
            session.pop('cashier', None)
            session.pop('cashier_id', None)
            return fail("Hết phiên đăng nhập hoặc tài khoản đã bị khoá, hãy đăng nhập lại quầy thu ngân.", 401)


# (mẫu đường dẫn, các vai được dùng) — xét từ trên xuống, khớp dòng đầu tiên là dừng. Không khớp dòng nào = chỉ Chủ.
MANAGER_PERMS = [
    (r'^/api/manager/system/',                                   ('Admin',)),
    (r'^/api/manager/table/(new|[^/]+/delete)$',                 ('Chủ', 'Admin')),
    (r'^/api/manager/tables?(/[^/]+)?$',                         ('Quản lí', 'Chủ', 'Admin')),
    (r'^/api/manager/(overview|dishes|menu|alacarte/.+|menu-item/.+|inventory/.+|pv.*)$', ('Quản lí', 'Chủ')),
]


def guard_manager_api():
    """Mọi API /api/manager/* (trừ đăng nhập / kiểm tra / đăng xuất) cần đăng nhập và đúng vai được phép."""
    path = request.path
    if not path.startswith('/api/manager/') or path in ('/api/manager/login', '/api/manager/me', '/api/manager/logout'):
        return None
    role = mgr_role()
    if not role:
        return fail("Hết phiên đăng nhập, hãy đăng nhập lại.", 401)
    allowed = next((roles for pat, roles in MANAGER_PERMS if re.match(pat, path)), ('Chủ',))
    if role not in allowed:
        return fail("Tài khoản của bạn không có quyền dùng chức năng này.", 403)
    return None


PIN_HASH_PREFIXES = ('pbkdf2:', 'scrypt:')


def pin_hash(pin):
    """Băm PIN trước khi lưu vào database (không lưu PIN dạng chữ)."""
    return generate_password_hash(str(pin), method='pbkdf2:sha256:100000')


def pin_check(stored, entered):
    """Kiểm tra PIN. Hỗ trợ cả PIN đã băm và PIN cũ chưa băm (để chạy được trước và sau khi chạy hash_pins.py)."""
    stored, entered = str(stored or ''), str(entered or '')
    if not stored or not entered:
        return False
    if stored.startswith(PIN_HASH_PREFIXES):
        return check_password_hash(stored, entered)
    return hmac.compare_digest(stored.encode('utf8'), entered.encode('utf8'))


def check_pin(pin):
    pin = str(pin or '').strip()
    if not re.fullmatch(r'\d{4}', pin):
        raise OrderError("Mã PIN phải gồm đúng 4 chữ số.")
    return pin


def register_guards(app):
    """Gắn 3 bước kiểm tra quyền chạy trước mỗi yêu cầu (đúng thứ tự: phục vụ, thu ngân, quản lí)."""
    app.before_request(guard_staff_api)
    app.before_request(guard_cashier_api)
    app.before_request(guard_manager_api)
