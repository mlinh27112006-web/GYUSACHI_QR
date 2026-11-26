"""Người phụ trách: Mai Linh
Mô tả: Điểm vào của ứng dụng. create_app() tạo Flask, gắn kiểm tra quyền, ghi nhật ký, bắt lỗi và đăng ký 9 controller.
Chạy: python app.py
"""
import os

from flask import Flask

import config
from core.audit import register_audit
from core.auth import register_guards
from core.errors import register_errors
from core.helpers import lan_ip


def create_app():
    app = Flask(__name__, template_folder='views', static_folder='static')
    app.secret_key = config.SECRET_KEY
    app.config.update(config.SESSION_CONFIG)
    app.config['SECRET_IS_DEFAULT'] = config.SECRET_IS_DEFAULT

    register_guards(app)      # kiểm tra quyền trước mỗi yêu cầu (phục vụ, thu ngân, quản lí)
    register_audit(app)       # ghi nhật ký sau thao tác của quản lí
    register_errors(app)      # lỗi /api/* luôn trả JSON

    from controllers.auth_controller import bp as auth_bp
    from controllers.staff_controller import bp as staff_bp
    from controllers.customer_controller import bp as customer_bp
    from controllers.kitchen_controller import bp as kitchen_bp
    from controllers.cashier_controller import bp as cashier_bp
    from controllers.report_controller import bp as report_bp
    from controllers.menu_controller import bp as menu_bp
    from controllers.inventory_controller import bp as inventory_bp
    from controllers.admin_controller import bp as admin_bp
    for bp in (auth_bp, staff_bp, customer_bp, kitchen_bp, cashier_bp,
               report_bp, menu_bp, inventory_bp, admin_bp):
        app.register_blueprint(bp)
    return app


app = create_app()

if __name__ == '__main__':
    print(f"\n  Máy tính:  http://127.0.0.1:5000\n  Điện thoại (cùng wifi):  http://{lan_ip()}:5000\n")
    app.run(debug=os.environ.get('FLASK_DEBUG') == '1', host='0.0.0.0', port=5000)
