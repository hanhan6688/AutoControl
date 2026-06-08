# 示例脚本：演示 OCR 点击、图像匹配点击和用户输入
#
# 可用的全局对象：
#   adb    - 基础 ADB 操作（点击、滑动、按键等）
#   ocr    - OCR 文字识别点击
#   image  - 图像模板匹配点击
#   input  - 用户输入请求（验证码、密码等）
#
# 使用方法：
#   1. 在前端选择设备
#   2. 运行此脚本

print("=== 脚本开始执行 ===")

# ========== 基础 ADB 操作 ==========
# adb.click(x, y)      - 点击坐标
# adb.tap(x, y)        - 同 click
# adb.swipe((x1, y1), (x2, y2), duration_ms) - 滑动
# adb.back()           - 返回键
# adb.home()           - Home 键
# adb.key(keycode)     - 发送按键事件
# adb.text("文字")     - 输入文字
# adb.wait(seconds)    - 等待
# adb.screenshot()     - 截图返回 PNG bytes

# ========== OCR 文字点击 ==========
# ocr.click("登录")           - 点击包含"登录"的文字
# ocr.click("登录", False)    - 精确匹配"登录"并点击
# ocr.find("搜索")            - 查找文字，返回 {"x", "y", "text", "score"} 或 None
# ocr.find_all()              - 返回屏幕上所有文字块

# ========== 图像匹配点击 ==========
# image.click("templates/btn.png")        - 点击匹配的图像
# image.click("btn.png", threshold=0.85)  - 使用更低阈值
# image.find("templates/icon.png")        - 查找图像，返回位置信息或 None
# image.wait_for("success.png", timeout=5) - 等待图像出现

# ========== 用户输入（验证码等） ==========
# input.prompt("请输入验证码")           - 弹窗请求用户输入
# input.prompt("请输入密码", "password") - 密码输入框
# input.verify_code()                    - 快捷方法：请求验证码
# input.password()                       - 快捷方法：请求密码

# ========== 示例场景 ==========

# 示例 1：OCR 点击登录按钮
# if ocr.click("登录"):
#     print("已点击登录按钮")
# else:
#     print("未找到登录按钮")

# 示例 2：查找并点击特定文字
# result = ocr.find("确定")
# if result:
#     print(f"找到文字: {result['text']}, 位置: ({result['x']}, {result['y']})")
#     adb.click(result['x'], result['y'])

# 示例 3：图像匹配点击
# if image.click("templates/login_btn.png"):
#     print("已点击图像按钮")
# else:
#     print("未找到图像")

# 示例 4：等待图像出现后操作
# if image.wait_for("templates/home_icon.png", timeout=10):
#     print("已进入首页")
#     ocr.click("我的")
# else:
#     print("等待超时")

# 示例 5：组合操作
# adb.back()
# adb.wait(1)
# if ocr.click("搜索"):
#     adb.wait(0.5)
#     adb.text("测试内容")
#     adb.key(66)  # Enter 键

# 示例 6：验证码输入
# 假设需要输入验证码
# if ocr.click("获取验证码"):
#     adb.wait(2)  # 等待短信
#     code = input.verify_code()  # 弹窗让用户输入验证码
#     if code:
#         adb.text(code)
#         print(f"已输入验证码: {code}")
#     else:
#         print("用户取消或超时")

# 示例 7：密码输入
# pwd = input.password("请输入登录密码")
# if pwd:
#     adb.text(pwd)
#     ocr.click("登录")

print("=== 脚本执行完成 ===")
