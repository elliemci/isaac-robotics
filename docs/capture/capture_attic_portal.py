#!/usr/bin/env python3
"""Headless-Firefox capture of the running Attic Portal (SimReadyPhysics).

Drives the real R-17 panel with selenium and saves PNGs / frame sequences to
docs/media/physical_ai_agent/. Does not touch project code. The portal must
already be running (source env.sh && ./scripts/restart.sh).

Usage: capture_attic_portal.py shots | videos   (ffmpeg encoding is done by make_media.sh)
"""
import os, subprocess, sys, time
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait

OUT = Path(__file__).resolve().parents[1] / "media" / "physical_ai_agent"
HOST = os.environ.get("VITE_SERVER_HOST") or subprocess.check_output(["hostname", "-I"], text=True).split()[0]
URL = f"http://127.0.0.1:{os.environ.get('ATTIC_PORTAL_CLIENT_PORT', '5177')}/?server={HOST}&signalingport=49101"
PANEL = ".r17-signal-panel"


def open_driver():
    o = Options(); o.add_argument("-headless"); o.set_preference("media.autoplay.default", 0)
    d = webdriver.Firefox(service=Service("/snap/bin/geckodriver"), options=o)
    d.set_window_size(1280, 1000)
    d.get(URL)
    w = WebDriverWait(d, 90)
    w.until(lambda d: d.execute_script("const v=document.getElementById('remote-video');return v&&v.readyState>=2&&v.videoWidth>0"))
    w.until(lambda d: "/Root/Workshop/Cube" in d.find_element(By.CSS_SELECTOR, PANEL).text)
    time.sleep(2)
    return d


def click(d, label):
    for b in d.find_elements(By.CSS_SELECTOR, PANEL + " button"):
        if b.text.strip().upper() == label.upper():
            d.execute_script("arguments[0].click();", b); return
    raise SystemExit(f"button not found: {label}")



FRAMES = OUT / "_frames"


def scroll_panel(d, bottom=True):
    d.execute_script("""
      let e = document.querySelector('.r17-signal-panel');
      while (e && e.scrollHeight <= e.clientHeight + 2) e = e.parentElement;
      if (e) e.scrollTop = arguments[0] ? e.scrollHeight : 0;""", bottom)
    time.sleep(0.5)


def shot(d, name):
    d.save_screenshot(str(OUT / f"{name}.png"))


def record(d, name, steps, tail=1.5, interval=0.15):
    """steps: list of (button_label | None, hold_seconds). Saves numbered frames and the measured fps."""
    fdir = FRAMES / name
    fdir.mkdir(parents=True, exist_ok=True)
    for f in fdir.glob("*.png"):
        f.unlink()
    n, t0 = 0, time.time()

    def grab_for(sec):
        nonlocal n
        end = time.time() + sec
        while time.time() < end:
            d.save_screenshot(str(fdir / f"{n:04d}.png")); n += 1
            time.sleep(interval)

    grab_for(0.8)
    for label, hold in steps:
        if label:
            click(d, label)
        grab_for(hold)
    grab_for(tail)
    (fdir / "fps.txt").write_text(f"{n / (time.time() - t0):.2f}\n")


def shots(d):
    shot(d, "01-portal-first-frame")
    click(d, "LEFT POSE -15"); time.sleep(2); shot(d, "02-cube-link-left")
    click(d, "RIGHT POSE +15"); time.sleep(2); shot(d, "02-cube-link-right")
    click(d, "HOME"); time.sleep(2)
    click(d, "DEFAULT VIEW"); time.sleep(2); shot(d, "03-camera-default")
    click(d, "CUBE FOCUS"); time.sleep(3); shot(d, "03-camera-cube-focus")
    click(d, "DEFAULT VIEW"); time.sleep(2)
    click(d, "SEMANTIC"); time.sleep(3); shot(d, "04-perception-semantic")
    click(d, "BEAUTY"); time.sleep(2)
    click(d, "LIDAR ON"); time.sleep(4); shot(d, "04-perception-lidar")
    click(d, "LIDAR OFF"); time.sleep(2)
    click(d, "run targets"); time.sleep(4); scroll_panel(d); shot(d, "05-simready-before")
    scroll_panel(d, False)


def videos(d):
    record(d, "cube-link", [("LEFT POSE -15", 2.5), ("HOME", 2.0), ("RIGHT POSE +15", 2.5), ("HOME", 1.5)])
    record(d, "perception", [("BEAUTY", 1.5), ("SEMANTIC", 3.0), ("BEAUTY", 1.0), ("LIDAR ON", 3.5), ("LIDAR OFF", 1.0)])
    scroll_panel(d)
    record(d, "physics", [(None, 1.0), ("\u25b6 PLAY", 8.0)], tail=0.5)
    shot(d, "06-physics-running")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    d = open_driver()
    try:
        {"shots": shots, "videos": videos}[sys.argv[1]](d)
    finally:
        d.quit()
