"""Người phụ trách: Mai Linh
Mô tả: Cấu hình ứng dụng đọc từ biến môi trường / file .env (không ghi mật khẩu trong mã nguồn).
"""
import os
import secrets
from datetime import timedelta
from pathlib import Path


def _load_env_file():
    """Đọc file .env (dạng KEY=VALUE) nếu có; biến môi trường đã đặt sẵn được ưu tiên."""
    path = Path(__file__).resolve().parent / '.env'
    if not path.exists():
        return
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file()

IS_PRODUCTION = bool(os.environ.get('RENDER') or os.environ.get('FLASK_ENV') == 'production'
                     or os.environ.get('APP_ENV') == 'production')

SECRET_KEY = os.environ.get('SECRET_KEY')
SECRET_IS_DEFAULT = False
if not SECRET_KEY:
    if IS_PRODUCTION:
        raise RuntimeError("Thiếu biến môi trường SECRET_KEY (chuỗi ngẫu nhiên dài) khi chạy production.")
    # Chạy thử trên máy mà chưa có .env: dùng khoá ngẫu nhiên cho lần chạy này (QR và phiên đăng nhập mất khi chạy lại).
    SECRET_KEY = secrets.token_hex(32)
    SECRET_IS_DEFAULT = True
    print("CẢNH BÁO: chưa đặt SECRET_KEY trong .env - đang dùng khoá tạm, mã QR cũ sẽ mất hiệu lực khi chạy lại.")

SESSION_CONFIG = dict(
    PERMANENT_SESSION_LIFETIME=timedelta(hours=14),         # đăng nhập giữ trong 1 ca
    SESSION_COOKIE_HTTPONLY=True,                           # JavaScript không đọc được cookie đăng nhập
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=IS_PRODUCTION,   # trên Render (https) chỉ gửi cookie qua https
)

DATABASE_URL = os.environ.get('DATABASE_URL')
DB_CONFIG = {
    'host': os.environ.get('DB_HOST', 'localhost'),
    'port': int(os.environ.get('DB_PORT', '5432')),
    'dbname': os.environ.get('DB_NAME', 'Gyusachi-qr'),
    'user': os.environ.get('DB_USER', 'postgres'),
    'password': os.environ.get('DB_PASSWORD', ''),
}
# Mọi kết nối chạy theo giờ Việt Nam dù máy chủ chạy UTC
PG_OPTIONS = '-c timezone=Asia/Ho_Chi_Minh'
