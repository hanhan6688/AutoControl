# 乐有家回归测试脚本
# 测试首页功能入口点击

launch("com.jjs.android.butler.test")
print("已启动乐有家应用")

# 等待页面加载
import time
time.sleep(2)

# 点击"新房"入口
auto_execute.click(text="新房", package="com.jjs.android.butler.test", fallback=(150, 1400))
print("点击新房入口")

time.sleep(2)

# 返回首页
adb.back()
print("返回首页")

time.sleep(1)

# 点击"二手房"入口
auto_execute.click(text="二手房", package="com.jjs.android.butler.test", fallback=(450, 1400))
print("点击二手房入口")

time.sleep(2)

adb.back()
print("返回首页")

print("回归测试完成")
