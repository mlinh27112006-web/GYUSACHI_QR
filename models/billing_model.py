"""Người phụ trách: Hồng Ngọc
Mô tả: Tính tiền: VAT, ưu đãi "đi 4 tính 3", voucher, tạo hoá đơn từ đơn đang mở.
"""

from datetime import datetime

from core.db import query
from models.settings_model import days_label, get_settings


PAY_METHODS = ('CASH', 'CARD', 'TRANSFER')


def is_holiday(d):
    h = set(get_settings()['holidays'])
    return d.strftime('%m-%d') in h or d.strftime('%Y-%m-%d') in h


def promo_auto(opened_at):
    """Ưu đãi "đi 4 tính 3" có áp dụng cho bàn mở lúc opened_at không? -> (True/False, lý do)."""
    if isinstance(opened_at, str):
        opened_at = datetime.fromisoformat(opened_at)
    if is_holiday(opened_at.date()):
        return False, "Ngày lễ - không áp dụng đi 4 tính 3"
    st = get_settings()
    promo = f"đi {st['group_size']} tính {st['group_size'] - 1}"
    if opened_at.hour < st['lunch_end_hour']:
        return True, f"Buffet trưa - {promo}"
    if opened_at.weekday() in st['dinner_days']:         # 0 = thứ 2 ... 6 = chủ nhật
        return True, f"Buffet tối {days_label(st['dinner_days'])} - {promo}"
    return False, f"Buffet tối ngoài {days_label(st['dinner_days'])} không áp dụng {promo}"


# Các mốc ưu đãi trên thẻ tích điểm (GIFT VOUCHER). Mỗi lần chỉ áp dụng 1 mốc,
# và không dùng chung với "đi 4 tính 3" (thẻ ghi: áp dụng 1 trong 2 chương trình, không áp dụng ngày Lễ/Tết).
VOUCHERS = [
    {"code": "P5",    "label": "Giảm 5%",                  "kind": "PERCENT", "value": 5},
    {"code": "GIFT2", "label": "Free 2 ly nước dưới 32k",  "kind": "GIFT",    "value": 2},
    {"code": "A100",  "label": "Voucher 100K",             "kind": "AMOUNT",  "value": 100000},
    {"code": "A150",  "label": "Voucher 150K",             "kind": "AMOUNT",  "value": 150000},
    {"code": "P15",   "label": "Giảm 15%",                 "kind": "PERCENT", "value": 15},
    {"code": "A300",  "label": "Voucher 300K",             "kind": "AMOUNT",  "value": 300000},
    {"code": "T20",   "label": "Vé buffet off 20%",        "kind": "TICKET",  "value": 20},
]


VOUCHER_MAP = {v['code']: v for v in VOUCHERS}


GIFT_DRINK_STATION = 'ST01'      # Quầy Pha Chế


GIFT_DRINK_MAX_PRICE = 32000     # "dưới 32k"


def compute_bill(o, items, guests=None, promo=None, voucher=None):
    """Tính hoá đơn. o: dòng đơn (có created_at dạng datetime), items: các dòng order_items.
    promo: None = tự động theo giờ/ngày, True = ép áp dụng, False = ép bỏ."""
    guests = int(guests or o['guests'] or 1)
    food_price = int(o['package_price'] or 0)
    drink_price = int(o['drink_price'] or 0)

    lines = []
    for i in items:
        if i['parent_id'] is None and i['kind'] in ('ALACARTE', 'COMBO') and i['status'] != 'CANCELLED':
            lines.append({"name": i['name'], "qty": i['qty'], "unit_price": int(i['unit_price']),
                          "amount": int(i['unit_price']) * i['qty']})

    food_amount = food_price * guests
    drink_amount = drink_price * guests
    extra_amount = sum(l['amount'] for l in lines)

    auto_ok, auto_reason = promo_auto(o['created_at'])
    apply = auto_ok if promo is None else bool(promo)
    st = get_settings()
    vat_rate = st['vat_percent'] / 100
    free = guests // st['group_size'] if (apply and food_price) else 0
    discount = free * food_price

    # VAT tính trên 1 đơn vị (vé buffet / nước / từng món) rồi nhân số lượng
    unit_vat = lambda price: int(round(price * vat_rate))
    food_vat = unit_vat(food_price) * guests
    drink_vat = unit_vat(drink_price) * guests
    for l in lines:
        l['unit_vat'] = unit_vat(l['unit_price'])
        l['vat'] = l['unit_vat'] * l['qty']
    discount_vat = unit_vat(food_price) * free

    subtotal = food_amount + drink_amount + extra_amount
    vat_full = food_vat + drink_vat + sum(l['vat'] for l in lines)

    # ---- mốc thẻ tích điểm ----
    v = VOUCHER_MAP.get(voucher) if voucher else None
    voucher_error = None
    voucher_label = None
    if voucher and not v:
        voucher_error = "Mốc ưu đãi không hợp lệ."
    elif v:
        voucher_label = v['label']
        if promo is True:
            voucher_error = "Chỉ áp dụng 1 trong 2: thẻ tích điểm hoặc đi 4 tính 3."
        elif is_holiday(o['created_at'].date() if hasattr(o['created_at'], 'date') else datetime.fromisoformat(str(o['created_at'])).date()):
            voucher_error = "Ngày Lễ/Tết không áp dụng ưu đãi thẻ tích điểm."
        else:
            free = 0
            gross = subtotal + vat_full
            if v['kind'] == 'PERCENT':
                discount = int(round(subtotal * v['value'] / 100))
                discount_vat = int(round(vat_full * v['value'] / 100))
            elif v['kind'] == 'TICKET':
                discount = int(round(food_amount * v['value'] / 100))
                discount_vat = int(round(food_vat * v['value'] / 100))
            elif v['kind'] == 'AMOUNT':
                amt = min(v['value'], gross)
                discount_vat = int(round(amt * vat_rate / (1 + vat_rate)))
                discount = amt - discount_vat
            else:   # GIFT: tối đa N ly nước ở quầy pha chế có giá dưới 32k, ưu tiên ly đắt nhất
                units = []
                for i in items:
                    if (i['parent_id'] is None and i['kind'] == 'ALACARTE' and i['status'] != 'CANCELLED'
                            and i.get('station_id') == GIFT_DRINK_STATION and int(i['unit_price']) < GIFT_DRINK_MAX_PRICE):
                        units += [int(i['unit_price'])] * i['qty']
                units = sorted(units, reverse=True)[:v['value']]
                discount = sum(units)
                discount_vat = sum(unit_vat(u) for u in units)
                if not units:
                    voucher_error = "Bàn chưa gọi nước nào dưới 32K ở quầy pha chế để tặng."
            if not voucher_error:
                voucher_label = v['label'] + (f" (giảm {discount + discount_vat:,}đ)".replace(',', '.'))
    voucher_applied = bool(v and not voucher_error)
    if v and voucher_error:
        discount = discount_vat = free = 0

    taxable = subtotal - discount
    vat = vat_full - discount_vat

    if voucher_applied:
        note = f"Thẻ tích điểm: {voucher_label}"
    elif v and voucher_error:
        note = voucher_error
    elif free:
        note = f"{auto_reason if promo is None else 'Thu ngân áp dụng ưu đãi nhóm'}: miễn phí {free} suất"
    elif promo is False:
        note = "Thu ngân bỏ ưu đãi nhóm"
    else:
        note = auto_reason

    return {
        "guests": guests,
        "food_name": o['package_name'], "food_price": food_price, "food_amount": food_amount,
        "drink_name": o['drink_name'], "drink_price": drink_price, "drink_amount": drink_amount,
        "lines": lines, "extra_amount": extra_amount,
        "promo_auto": auto_ok, "promo_applied": bool(free), "promo_free": free,
        "voucher": voucher if v else None, "voucher_applied": voucher_applied,
        "voucher_label": voucher_label if voucher_applied else None, "voucher_error": voucher_error,
        "vouchers": VOUCHERS,
        "promo_note": note, "discount": discount, "discount_vat": discount_vat,
        "food_vat": food_vat, "drink_vat": drink_vat,
        "subtotal": subtotal, "vat_rate": vat_rate, "vat": vat, "total": taxable + vat,
    }


def load_order_for_bill(order_id, cur=None):
    """Đọc đơn + món để tính bill. Có cur thì đọc trong transaction (khoá dòng đơn)."""
    sql_o = """
        SELECT o.id, o.table_id, o.guests, o.status, o.created_at,
               to_char(o.created_at, 'HH24:MI DD/MM') AS opened_at,
               p.name AS package_name, p.price AS package_price,
               d.name AS drink_name,   d.price AS drink_price
        FROM orders o
        LEFT JOIN packages p ON p.id = o.package_id
        LEFT JOIN packages d ON d.id = o.drink_package_id
        WHERE o.id = %s""" + (" FOR UPDATE OF o" if cur else "")
    sql_i = """SELECT id, parent_id, kind, name, qty, unit_price, status, station_id
               FROM order_items WHERE order_id = %s ORDER BY id"""
    if cur:
        cur.execute(sql_o, (order_id,)); o = cur.fetchone()
        cur.execute(sql_i, (order_id,)); items = cur.fetchall()
    else:
        o = query(sql_o, (order_id,), one=True)
        items = query(sql_i, (order_id,))
    return o, items


def parse_promo(v):
    """'on' -> True, 'off' -> False, còn lại -> None (tự động)."""
    return True if v in ('on', True) else False if v in ('off', False) else None


def pending_count(items):
    return sum(1 for i in items if i['parent_id'] is not None or i['kind'] in ('PACKAGE', 'ALACARTE')
               if i['status'] in ('NEW', 'DOING'))
