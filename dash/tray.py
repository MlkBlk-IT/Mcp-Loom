#!/usr/bin/env pythonw
"""loom-dash system tray launcher."""
import os, sys, subprocess, webbrowser, threading, time

DASH_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(DASH_DIR, "server.py")
PYTHON = sys.executable.replace("python.exe", "pythonw.exe")
if not os.path.exists(PYTHON):
    PYTHON = sys.executable

proc = None

def start_server():
    global proc
    if proc is not None and proc.poll() is None:
        return
    proc = subprocess.Popen([sys.executable, SERVER, "--db", r"C:\Users\Tech\.loom\loom.db"], cwd=DASH_DIR,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=0x08000000)  # CREATE_NO_WINDOW

def stop_server():
    global proc
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try: proc.wait(timeout=5)
        except Exception: proc.kill()
    proc = None

def open_dash(icon, item):
    webbrowser.open("http://127.0.0.1:8775")

def restart(icon, item):
    stop_server()
    time.sleep(1)
    start_server()
    webbrowser.open("http://127.0.0.1:8775")

def quit_app(icon, item):
    stop_server()
    icon.stop()

def main():
    import pystray
    from PIL import Image, ImageDraw
    start_server()
    # build icon
    img = Image.new("RGB", (64, 64), (11, 15, 20))
    d = ImageDraw.Draw(img)
    d.ellipse((8, 8, 56, 56), fill=(63, 182, 139))
    d.text((24, 20), "L", fill=(255, 255, 255))
    menu = pystray.Menu(
        pystray.MenuItem("Open Dashboard", open_dash, default=True),
        pystray.MenuItem("Restart Server", restart),
        pystray.MenuItem("Quit", quit_app),
    )
    icon = pystray.Icon("loom-dash", img, "loom-dash", menu)
    icon.run()

if __name__ == "__main__":
    main()
