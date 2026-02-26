
import subprocess
import sys

def run(cmd):
    print(f"Running: {cmd}")
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"Error: {res.stderr}")
        return False
    print(res.stdout)
    return True

cmds = [
    "git add .",
    'git commit -m "Fix planeta-pancho products, master login, and cleanup"',
    "git push server1 main",
    "git push origin main"
]

for c in cmds:
    if not run(c):
        print("Stopping due to error.")
        break
