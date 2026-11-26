from core.auth import pin_hash, pin_check


def test_pin_duoc_bam_va_kiem_tra_dung():
    h = pin_hash('1234')
    assert h.startswith('pbkdf2:')
    assert pin_check(h, '1234') is True
    assert pin_check(h, '9999') is False


def test_pin_cu_chua_bam_van_dang_nhap_duoc():
    assert pin_check('1234', '1234') is True
    assert pin_check('1234', '0000') is False


def test_pin_rong_bi_tu_choi():
    assert pin_check('', '1234') is False
    assert pin_check('1234', '') is False
