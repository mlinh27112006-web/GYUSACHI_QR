"""Người phụ trách: Nguyên An
Mô tả: Kho phục vụ: trạng thái hết/sắp hết và cách tự trừ kho.
"""

from core.helpers import OrderError, num


PV_FIELDS = "k.ma_vt, k.ma_nhom, n.ten_nhom, k.ten_vt, k.dvt, k.so_luong, k.ton_toi_thieu, k.ma_update, k.kieu_tru, k.dinh_muc, k.ghi_chu, k.dang_dung"


def pv_row(r):
    d = dict(r)
    for k in ('so_luong', 'ton_toi_thieu', 'dinh_muc'):
        d[k] = float(d[k])
    d['out'] = d['so_luong'] <= 0
    d['low'] = (not d['out']) and d['ton_toi_thieu'] > 0 and d['so_luong'] <= d['ton_toi_thieu']
    return d


def pv_auto_fields(data, cur_ma_update=None):
    """Đọc cách cập nhật: ma_update 2 = thủ công, 1 = tự trừ (cần kieu_tru + định mức > 0)."""
    mu = int(data.get('ma_update', cur_ma_update or 2))
    if mu == 2:
        return 2, None, 0
    if mu != 1:
        raise OrderError("Cách cập nhật chỉ nhận 1 (tự trừ) hoặc 2 (thủ công).")
    kieu = data.get('kieu_tru')
    if kieu not in ('KHACH', 'NGAY'):
        raise OrderError("Tự trừ cần chọn trừ theo số khách hay theo ngày.")
    dm = num(data.get('dinh_muc'), "Định mức", minimum=0, maximum=100000)
    if dm <= 0:
        raise OrderError("Tự trừ cần định mức lớn hơn 0.")
    return 1, kieu, dm
