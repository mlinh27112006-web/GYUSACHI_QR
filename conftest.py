"""Người phụ trách: Mai Linh
Mô tả: Để pytest tìm thấy app.py, core/, models/ ở thư mục gốc khi chạy: pytest tests/<tên file>.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
