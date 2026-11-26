import pytest

from core.helpers import OrderError
from models.inventory_model import pv_row, pv_auto_fields


def test_vat_tu_het_hang():
    d = pv_row({'so_luong': 0, 'ton_toi_thieu': 5, 'dinh_muc': 1})
    assert d['out'] is True and d['low'] is False


def test_vat_tu_sap_het():
    d = pv_row({'so_luong': 3, 'ton_toi_thieu': 5, 'dinh_muc': 1})
    assert d['low'] is True and d['out'] is False


def test_cap_nhat_thu_cong():
    assert pv_auto_fields({'ma_update': 2}) == (2, None, 0)


def test_tu_tru_phai_co_dinh_muc():
    with pytest.raises(OrderError):
        pv_auto_fields({'ma_update': 1, 'kieu_tru': 'KHACH', 'dinh_muc': 0})
