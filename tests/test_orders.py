from flask import session

from app import app
from controllers.staff_controller import is_customer_request


def test_khach_quet_qr_la_khach():
    with app.test_request_context('/'):
        assert is_customer_request({'source': 'QR'}) is True


def test_nguoi_chua_dang_nhap_bi_coi_la_khach():
    with app.test_request_context('/'):
        assert is_customer_request({}) is True


def test_nhan_vien_da_dang_nhap_khong_phai_khach():
    with app.test_request_context('/'):
        session['staff'] = 1
        assert is_customer_request({}) is False
