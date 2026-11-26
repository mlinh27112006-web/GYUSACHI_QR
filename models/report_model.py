"""Người phụ trách: Hồng Ngọc
Mô tả: Hỗ trợ báo cáo: điều kiện hoá đơn đã thanh toán, doanh thu theo ngày, ghi CSV an toàn.
"""

from core.db import query


PAID = "o.status = 'CLOSED' AND o.paid_at IS NOT NULL AND o.voided_at IS NULL"   # hoá đơn đã thanh toán và chưa bị huỷ


def daily_series(d_from, d_to):
    rows = query(f"""
        SELECT to_char(g.d, 'YYYY-MM-DD') AS day,
               COALESCE(SUM(o.total), 0)::bigint AS revenue, COUNT(o.id)::int AS bills
        FROM generate_series(%s::date, %s::date, '1 day') AS g(d)
        LEFT JOIN orders o ON o.paid_at::date = g.d AND {PAID}
        GROUP BY g.d ORDER BY g.d
    """, (d_from, d_to))
    return [dict(r) for r in rows]


class SafeCsv:
    """Bọc csv.writer: ô văn bản bắt đầu bằng = + - @ sẽ thêm dấu ' phía trước để Excel không chạy như công thức."""
    def __init__(self, writer):
        self.w = writer

    def writerow(self, row):
        def safe(c):
            if isinstance(c, str) and c.lstrip(' \t\r\n\x00\x0b\x0c')[:1] in ('=', '+', '-', '@'):
                return "'" + c                      # cả trường hợp có khoảng trắng đứng trước công thức
            if isinstance(c, str) and c[:1] in ('\t', '\r'):
                return "'" + c
            return c
        self.w.writerow([safe(c) for c in row])
