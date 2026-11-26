"""Người phụ trách: Mai Linh
Mô tả: Bắt lỗi toàn ứng dụng: lỗi ở /api/* luôn trả JSON dễ đọc.
"""

from flask import request, jsonify, current_app


def handle_any_error(e):
    """Lỗi ở /api/* luôn trả JSON (không để trình duyệt nhận trang HTML khó đọc)."""
    from werkzeug.exceptions import HTTPException
    if request.path.startswith('/api/'):
        if isinstance(e, HTTPException):
            return jsonify({"success": False, "message": e.description}), e.code
        current_app.logger.exception("Lỗi không lường trước ở %s", request.path)
        return jsonify({"success": False, "message": "Lỗi hệ thống, vui lòng thử lại."}), 500
    if isinstance(e, HTTPException):
        return e
    raise e


def register_errors(app):
    app.register_error_handler(Exception, handle_any_error)
