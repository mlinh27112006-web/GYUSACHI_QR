from datetime import datetime

from models import billing_model as b

FAKE = {'group_size': 4, 'lunch_end_hour': 15, 'dinner_days': [0, 1, 2, 3]}   # tối thứ 2 đến thứ 5


def _gia_lap(monkeypatch, ngay_le=False):
    monkeypatch.setattr(b, 'get_settings', lambda *a, **k: FAKE)
    monkeypatch.setattr(b, 'is_holiday', lambda d: ngay_le)


def test_buffet_trua_ap_dung_di_4_tinh_3(monkeypatch):
    _gia_lap(monkeypatch)
    ok, _ = b.promo_auto(datetime(2026, 12, 8, 12, 0))       # thứ 3, 12 giờ
    assert ok is True


def test_ngay_le_khong_ap_dung(monkeypatch):
    _gia_lap(monkeypatch, ngay_le=True)
    ok, _ = b.promo_auto(datetime(2026, 12, 8, 12, 0))
    assert ok is False


def test_toi_cuoi_tuan_khong_ap_dung(monkeypatch):
    _gia_lap(monkeypatch)
    ok, _ = b.promo_auto(datetime(2026, 12, 12, 19, 0))      # thứ 7, 19 giờ
    assert ok is False
