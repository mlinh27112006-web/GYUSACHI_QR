# Lệnh commit cho Nguyên An - chạy trong thư mục repo đã clone (vd D:/gyusachi), SAU KHI:
#   1. git checkout develop; git pull; git checkout -b feature/nguyen-an-kitchen
#   2. giải nén nguyen-an.zip đè vào thư mục repo
#   3. git status chỉ được thấy file của bạn (không có .env, static)

git add SQL
git commit -m '[DOCS] feat: thêm 23 file SQL tạo CSDL và hướng dẫn thứ tự chạy'

git add controllers/kitchen_controller.py views/kitchen
git commit -m '[KITCHEN] feat: thêm trang bếp (danh sách món theo trạm, đổi trạng thái)'

git add controllers/menu_controller.py views/manager/_menu.html
git commit -m '[MENU] feat: thêm quản lí thực đơn, món lẻ, combo'

git add controllers/inventory_controller.py models/inventory_model.py views/manager/_pv.html views/manager/_moves.html
git commit -m '[STOCK] feat: thêm kho phục vụ và lịch sử nhập xuất'

git add tests/test_inventory.py
git commit -m '[STOCK] test: kiểm tra trạng thái và cách tự trừ kho'

git add tests/test_structure.py
git commit -m '[TEST] test: kiểm tra cấu trúc MVC'

git push -u origin feature/nguyen-an-kitchen
