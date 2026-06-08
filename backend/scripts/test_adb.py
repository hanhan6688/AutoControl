import subprocess, sys
udid = sys.argv[1]
r = subprocess.run(["adb", "-s", udid, "shell", "getprop", "ro.product.model"], capture_output=True, text=True)
print(f"Model: {r.stdout.strip()}")
