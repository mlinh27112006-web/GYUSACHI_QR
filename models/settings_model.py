"""Người phụ trách: Mai Linh
Mô tả: Cấu hình chỉnh được ở trang Quản lí (VAT, giờ trưa, đi 4 tính 3, ngày lễ) và tài khoản nhận chuyển khoản.
"""

import re
import time
from datetime import datetime

from core.db import query
from core.helpers import OrderError


VAT_RATE = 0.08                                          # VAT 8%


LUNCH_END_HOUR = 15                                      # mở bàn trước 15:00 là buffet trưa


GROUP_SIZE = 4                                           # đi 4 ...


# Ngày lễ KHÔNG áp dụng "đi 4 tính 3". 'MM-DD' = lặp mỗi năm, 'YYYY-MM-DD' = riêng năm đó.
HOLIDAYS_YEARLY = {'01-01', '04-30', '05-01', '09-02', '12-24', '12-25'}


HOLIDAYS_ONCE = {f'2027-02-{d:02d}' for d in range(5, 12)}      # Tết Đinh Mùi 2027 (30 Tết - mùng 5)


SETTING_KEYS = ('cfg_vat_percent', 'cfg_lunch_end_hour', 'cfg_group_size', 'cfg_dinner_days', 'cfg_holidays')


_SETTINGS_CACHE = {'at': 0.0, 'val': None}


def default_settings():
    return {"vat_percent": VAT_RATE * 100, "lunch_end_hour": LUNCH_END_HOUR, "group_size": GROUP_SIZE,
            "dinner_days": [0, 1, 2, 3],                      # 0 = thứ 2 ... 6 = chủ nhật
            "holidays": sorted(HOLIDAYS_YEARLY | HOLIDAYS_ONCE)}


def get_settings(force=False):
    now = time.time()
    if not force and _SETTINGS_CACHE['val'] is not None and now - _SETTINGS_CACHE['at'] < 5:
        return _SETTINGS_CACHE['val']
    st = default_settings()
    try:
        rows = {r['key']: r['value'] for r in query(
            "SELECT key, value FROM app_settings WHERE key = ANY(%s)", (list(SETTING_KEYS),))}
    except Exception:
        rows = {}                  # chưa chạy file 17 -> dùng mặc định
    try:
        if 'cfg_vat_percent' in rows:     st['vat_percent'] = float(rows['cfg_vat_percent'])
        if 'cfg_lunch_end_hour' in rows:  st['lunch_end_hour'] = int(rows['cfg_lunch_end_hour'])
        if 'cfg_group_size' in rows:      st['group_size'] = int(rows['cfg_group_size'])
        if 'cfg_dinner_days' in rows:
            st['dinner_days'] = sorted({int(x) for x in rows['cfg_dinner_days'].split(',') if x.strip() != ''})
        if 'cfg_holidays' in rows:
            st['holidays'] = sorted({x.strip() for x in rows['cfg_holidays'].split(',') if x.strip()})
    except (TypeError, ValueError):
        st = default_settings()    # dữ liệu hỏng -> quay về mặc định, không làm sập thu ngân
    _SETTINGS_CACHE.update(at=now, val=st)
    return st


def days_label(days):
    """[0,1,2,3] -> 'T2-T5'; [0,2,4] -> 'T2, T4, T6'."""
    names = ['T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'CN']
    d = sorted(days)
    if not d:
        return 'không ngày nào'
    if d == list(range(d[0], d[-1] + 1)) and len(d) > 2:
        return f"{names[d[0]]}-{names[d[-1]]}"
    return ', '.join(names[x] for x in d)


def parse_holiday(x):
    """'MM-DD' (hằng năm) hoặc 'YYYY-MM-DD' (riêng năm đó) -> chuỗi chuẩn, hoặc báo lỗi."""
    x = str(x).strip()
    try:
        if re.fullmatch(r'\d{2}-\d{2}', x):
            datetime.strptime('2000-' + x, '%Y-%m-%d')          # 2000 là năm nhuận, cho phép 02-29
        elif re.fullmatch(r'\d{4}-\d{2}-\d{2}', x):
            datetime.strptime(x, '%Y-%m-%d')
        else:
            raise ValueError
    except ValueError:
        raise OrderError(f"Ngày lễ “{x}” không hợp lệ (dùng dd/mm hoặc dd/mm/yyyy).")
    return x


PAY_KEYS = ('cfg_bank_id', 'cfg_bank_account', 'cfg_bank_holder')


def payment_config():
    rows = {r['key']: r['value'] for r in query("SELECT key, value FROM app_settings WHERE key = ANY(%s)", (list(PAY_KEYS),))}
    return {"bank_id": rows.get('cfg_bank_id', ''), "account": rows.get('cfg_bank_account', ''),
            "holder": rows.get('cfg_bank_holder', '')}
