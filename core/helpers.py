"""Người phụ trách: Mai Linh
Mô tả: Hàm và hằng số dùng chung: giờ Việt Nam, lỗi nghiệp vụ (OrderError), trả lỗi JSON (fail), gom món theo nhóm, đọc ngày/số.
"""

import socket
from datetime import datetime, timedelta, timezone

from flask import request, jsonify


# Thứ tự hiển thị các nhóm món (giống thứ tự trong menu giấy)
CATEGORY_ORDER = [
    'Khai vị', 'Salad', 'Kim chi', 'Thịt nướng', 'Set Thịt Nướng', 'Hải sản nướng',
    'Sushi', 'Sashimi', 'Lẩu', 'Topping lẩu', 'Cơm', 'Pizza', 'Mì', 'Món ăn thêm', 'Soup',
    'Topping', 'Special', 'Tráng miệng', 'Combo',
    'Soda', 'Nước trái cây', 'Cocktail', 'Trà', 'Nước ngọt', 'Rượu', 'Bia', 'Thức uống',
]


FOOD_PACKAGE_MIN_PRICE = 150000     # từ 150K trở lên là buffet đồ ăn, dưới là buffet nước


BUFFET_MINUTES = 120                # thời gian gọi món buffet, tính từ món đầu tiên của bàn


BUFFET_WARN_MINUTES = 15            # báo sắp hết giờ khi còn ngần này phút


DESSERT_CATEGORY = 'Tráng miệng'    # hết giờ thì khách (qua QR) chỉ còn gọi được nhóm này


def group_by_category(rows):
    """[{category, ...}] -> [{name, items:[...]}] theo đúng thứ tự menu."""
    groups = {}
    for r in rows:
        groups.setdefault(r['category'], []).append(r)

    def sort_key(name):
        return CATEGORY_ORDER.index(name) if name in CATEGORY_ORDER else 99

    return [{"name": name, "items": groups[name]}
            for name in sorted(groups, key=sort_key)]


VN_TZ = timezone(timedelta(hours=7))      # giờ Việt Nam (máy chủ Render chạy giờ UTC; VN không có giờ mùa hè)


def vn_now():
    """Giờ hiện tại ở Việt Nam (không kèm múi giờ). Dùng hàm này để so sánh ngày/giờ (ví dụ gói buffet chỉ áp dụng một số thứ trong tuần)."""
    return datetime.now(VN_TZ).replace(tzinfo=None)


class OrderError(Exception):
    """Lỗi nghiệp vụ (trả về cho người dùng đọc được)."""


def fail(message, status=400):
    return jsonify({"success": False, "message": message}), status


def date_range():
    """Đọc ?from=YYYY-MM-DD&to=YYYY-MM-DD (mặc định 7 ngày gần nhất). Trả (from, to) dạng chuỗi."""
    today = vn_now().date()
    try:
        d_to = datetime.strptime(request.args.get('to', ''), '%Y-%m-%d').date()
    except ValueError:
        d_to = today
    try:
        d_from = datetime.strptime(request.args.get('from', ''), '%Y-%m-%d').date()
    except ValueError:
        d_from = d_to - timedelta(days=6)
    if d_from > d_to:
        d_from, d_to = d_to, d_from
    if (d_to - d_from).days > 366:
        d_from = d_to - timedelta(days=366)
    return d_from.isoformat(), d_to.isoformat()


def clean_name(v, limit):
    """Tên món: bỏ khoảng trắng thừa, không được rỗng."""
    v = ' '.join(str(v or '').split())
    if not v:
        raise OrderError("Hãy nhập tên.")
    if len(v) > limit:
        raise OrderError(f"Tên quá dài (tối đa {limit} ký tự).")
    return v


def vnd(n):
    return f"{int(n):,}đ".replace(',', '.')


def parse_days(text):
    """'1,2,3' -> [1,2,3]; bỏ qua phần tử sai (không gây lỗi 500), chỉ nhận thứ 1..7."""
    out = []
    for x in str(text or '').split(','):
        x = x.strip()
        if x.isdigit() and 1 <= int(x) <= 7:
            out.append(int(x))
    return out


def num(v, field, minimum=0, maximum=10_000_000):
    """Đọc số (cho phép dấu phẩy thập phân kiểu Việt Nam)."""
    try:
        x = float(str(v).strip().replace(',', '.'))
    except (TypeError, ValueError):
        raise OrderError(f"{field} phải là một số.")
    if x != x or x < minimum or x > maximum:
        raise OrderError(f"{field} không hợp lệ.")
    return round(x, 2)


def parse_day(s):
    try:
        return datetime.strptime(str(s), '%Y-%m-%d').date()
    except ValueError:
        raise OrderError("Ngày không hợp lệ.")


def lan_ip():
    """Địa chỉ IP của máy trong mạng nội bộ (wifi) - để điện thoại cùng wifi quét QR vào được."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))          # không gửi gói tin nào, chỉ để hệ điều hành chọn card mạng
        return s.getsockname()[0]
    except OSError:
        return '127.0.0.1'
    finally:
        s.close()
