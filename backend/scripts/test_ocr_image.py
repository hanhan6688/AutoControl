# 测试脚本：OCR 和图像匹配功能演示
# 请确保设备已连接并解锁

print("开始测试 OCR 和图像功能...")

# 等待一下确保设备就绪
adb.wait(1)

# 测试 OCR：获取屏幕上所有文字
print("\n--- OCR 测试 ---")
all_text = ocr.find_all()
print(f"屏幕上找到 {len(all_text)} 个文字块:")
for i, block in enumerate(all_text[:10]):  # 只显示前10个
    print(f"  {i+1}. '{block['text']}' @ ({block['x']}, {block['y']}) score={block['score']:.2f}")

# 测试查找特定文字
print("\n--- 查找文字 ---")
test_texts = ["确定", "取消", "登录", "搜索", "设置"]
for text in test_texts:
    result = ocr.find(text)
    if result:
        print(f"✓ 找到 '{text}' @ ({result['x']}, {result['y']})")
    else:
        print(f"✗ 未找到 '{text}'")

# 测试截图功能
print("\n--- 截图测试 ---")
png_data = adb.screenshot()
print(f"截图大小: {len(png_data)} bytes")

print("\n测试完成!")
