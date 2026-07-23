import subprocess
import time
import sys

def login():
    print("[GitHub] Requesting fresh device authentication code...")
    proc = subprocess.Popen(
        [r"C:\Program Files\GitHub CLI\gh.exe", "auth", "login", "--hostname", "github.com", "-p", "https", "-w"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )
    
    code_found = False
    for line in iter(proc.stdout.readline, ''):
        print(line, end='', flush=True)
        if "one-time code" in line:
            code_found = True
            
    proc.wait()
    if proc.returncode == 0:
        print("\n[GitHub] Authorization SUCCESSFUL!")
    else:
        print(f"\n[GitHub] Authorization finished with return code {proc.returncode}")

if __name__ == '__main__':
    login()
