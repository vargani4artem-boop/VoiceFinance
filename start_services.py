import os
import sys
import subprocess
import time

CWD = os.path.dirname(os.path.abspath(__file__))

# On Windows, DETACHED_PROCESS = 0x00000008, CREATE_NEW_PROCESS_GROUP = 0x00000200
DETACHED = 0x00000008 | 0x00000200 if sys.platform == 'win32' else 0

def start_all():
    print("[Launcher] Starting Server, Cloudflare Tunnel, and Telegram Bot in detached OS processes...")
    
    # 1. Start Server
    p_server = subprocess.Popen(
        [sys.executable, "server.py"],
        cwd=CWD,
        creationflags=DETACHED,
        close_fds=True
    )
    print(f"[Launcher] Server started (PID: {p_server.pid})")

    time.sleep(1)

    # 2. Start Cloudflare Tunnel
    cloudflared_bin = os.path.join(CWD, "cloudflared.exe")
    if os.path.exists(cloudflared_bin):
        p_tunnel = subprocess.Popen(
            [cloudflared_bin, "tunnel", "--url", "http://127.0.0.1:8000"],
            cwd=CWD,
            creationflags=DETACHED,
            close_fds=True
        )
        print(f"[Launcher] Cloudflare Tunnel started (PID: {p_tunnel.pid})")
    
    time.sleep(2)

    # 3. Start Bot
    p_bot = subprocess.Popen(
        [sys.executable, "bot.py"],
        cwd=CWD,
        creationflags=DETACHED,
        close_fds=True
    )
    print(f"[Launcher] Telegram Bot started (PID: {p_bot.pid})")
    print("[Launcher] All services are now running detached in Windows OS background!")

if __name__ == '__main__':
    start_all()
