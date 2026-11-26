import re
from pathlib import Path

from app import app

ROOT = Path(__file__).resolve().parent.parent
CONTROLLERS = ['auth', 'staff', 'customer', 'kitchen', 'cashier', 'report', 'menu', 'inventory', 'admin']


def _routes():
    return [r for r in app.url_map.iter_rules() if r.endpoint != 'static']


def test_du_83_route():
    assert len(_routes()) == 83


def test_dang_ky_du_9_controller():
    assert sorted(app.blueprints) == sorted(CONTROLLERS)
    for name in CONTROLLERS:
        assert (ROOT / 'controllers' / f'{name}_controller.py').exists()


def test_cau_truc_thu_muc_mvc():
    for p in ['core/db.py', 'core/helpers.py', 'core/auth.py', 'core/audit.py', 'core/errors.py',
              'models/staff_model.py', 'models/table_model.py', 'models/settings_model.py',
              'models/billing_model.py', 'models/report_model.py', 'models/order_model.py',
              'models/inventory_model.py', 'views/home/index.html', 'views/manager/quanli.html']:
        assert (ROOT / p).exists(), p


def test_controller_khong_goi_cheo_nhau():
    """Controller chỉ dùng core/ và models/, không import controller khác."""
    for f in (ROOT / 'controllers').glob('*_controller.py'):
        text = f.read_text(encoding='utf-8')
        assert not re.search(r'^\s*(from|import)\s+controllers\.', text, re.M), f.name


def test_moi_file_py_co_nguoi_phu_trach():
    for folder in ['core', 'models', 'controllers']:
        for f in (ROOT / folder).glob('*.py'):
            assert 'Người phụ trách:' in f.read_text(encoding='utf-8')[:200], f.name


def test_template_duoc_goi_deu_ton_tai():
    for f in (ROOT / 'controllers').glob('*_controller.py'):
        for name in re.findall(r"'([\w/]+\.html)'", f.read_text(encoding='utf-8')):
            if name.endswith('goimon_ban.html'):
                continue                                   # mẫu dự phòng, không bắt buộc có
            assert (ROOT / 'views' / name).exists(), name
