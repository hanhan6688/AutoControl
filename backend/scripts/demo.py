
#!/usr/bin/env python3
"""Demo script: launch app and perform basic UI operations."""
auto_execute.launch("com.jjs.android.butler.test")
auto_execute.wait(0.5)
auto_execute.click(xpath="//android.widget.TextView[@resource-id=\"com.jjs.android.butler.test:id/home_txt_search\"]")
auto_execute.wait(0.5)
auto_execute.input("深圳翠园中学")
