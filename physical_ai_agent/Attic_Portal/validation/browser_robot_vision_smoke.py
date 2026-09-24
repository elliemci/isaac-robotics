#!/usr/bin/env python3
"""Focused browser check for R-17 Robot Vision BEAUTY / SEMANTIC modes.

Implements the ROBOT_VISION_CONTRACT validation checklist against the running
Attic Portal:

1. `SemanticSegmentation` and `SemanticIdMap` are runtime frame keys.
2. `semanticUniqueIds` has at least 3 IDs once SEMANTIC is active.
3. `semanticNonzeroPixels > 0`.
4. The decoded ID map includes `memory_cube` and `retrieval_target`.
5. The SEMANTIC video is visibly distinct from the BEAUTY video.
6. Repeated BEAUTY/SEMANTIC switching keeps `renderer_owner_count == 1` and one
   WebRTC video track.
7. The protected Attic source USD hashes are unchanged.

Environment overrides: URL, STATE_URL, FIREFOX_BIN, GECKODRIVER, ARTIFACT_DIR,
SEMANTICS_LAYER, PROTECTED_USD_DIR.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import urllib.request
from pathlib import Path

from PIL import Image, ImageChops, ImageStat
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait

ROOT = Path(__file__).resolve().parents[1]
SESSION_ROOT = ROOT.parent
CLIENT_PORT = os.environ.get('ATTIC_PORTAL_CLIENT_PORT', '5176')
SERVER_HOST = os.environ.get('VITE_SERVER_HOST', '127.0.0.1')
SIGNALING_PORT = os.environ.get('ATTIC_PORTAL_SIGNALING_PORT', '49101')
HEALTH_PORT = os.environ.get('ATTIC_PORTAL_HEALTH_PORT', '8082')
URL = os.environ.get('URL', f'http://127.0.0.1:{CLIENT_PORT}/?server={SERVER_HOST}&signalingport={SIGNALING_PORT}')
STATE_URL = os.environ.get('STATE_URL', f'http://127.0.0.1:{HEALTH_PORT}/state.json')
FIREFOX_BIN = os.environ.get('FIREFOX_BIN', shutil.which('firefox') or 'firefox')
GECKODRIVER = os.environ.get('GECKODRIVER', shutil.which('geckodriver') or 'geckodriver')
ARTIFACT_DIR = Path(os.environ.get('ARTIFACT_DIR', str(ROOT / 'artifacts')))
SEMANTICS_LAYER = Path(os.environ.get('SEMANTICS_LAYER', str(ROOT / 'usd' / 'R17_Semantics.usda')))
PROTECTED_USD_DIR = Path(os.environ.get('PROTECTED_USD_DIR', str(SESSION_ROOT / 'Attic_NVIDIA')))

# The protected mission sources must never be written by the viewer.
PROTECTED_USD_HASHES = {
    'Attic_NVIDIA.usd': '12db25c282bcf57ba371381d96c5ea11dd0709386493b27e99b2c6c70992502c',
    'OldAttic_Mission.usda': '80b9adfcef7a587caddd0eb04dfa85d84baff52f4bb80712d9f19bad29657739',
}
REQUIRED_OUTPUT_KEYS = ('LdrColor', 'SemanticSegmentation', 'SemanticIdMap')


def get_state() -> dict:
    with urllib.request.urlopen(STATE_URL, timeout=2) as response:
        return json.load(response)


def wait_mode(mode: str, timeout: float = 15.0) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = get_state()
        r17 = last['r17']
        if r17.get('status') == 'READY' and r17.get('renderMode') == mode:
            return last
        time.sleep(0.05)
    raise AssertionError({'wantedMode': mode, 'last': last})


def click_button(driver: webdriver.Firefox, label: str) -> None:
    for button in driver.find_elements(By.CSS_SELECTOR, '.r17-render-controls button'):
        if button.text.strip() == label:
            driver.execute_script('arguments[0].click();', button)
            return
    raise AssertionError(f'button not found: {label}')


def capture(driver: webdriver.Firefox, name: str, video) -> tuple[Path, dict]:
    path = ARTIFACT_DIR / name
    driver.save_screenshot(str(path))
    image = Image.open(path).convert('RGB')
    rect = video.rect
    left = max(0, int(rect['x']))
    top = max(0, int(rect['y']))
    right = min(image.width, int(rect['x'] + rect['width'] * 0.68))
    bottom = min(image.height, int(rect['y'] + rect['height']))
    crop = image.crop((left, top, right, bottom))
    stat = ImageStat.Stat(crop)
    return path, {'meanRgb': sum(stat.mean) / 3.0, 'variance': sum(stat.var) / 3.0, 'image': crop}


def assert_semantics_layer() -> None:
    text = SEMANTICS_LAYER.read_text(encoding='utf-8')
    for needle in ('SemanticsAPI:label', 'retrieval_target', 'memory_cube', 'attic_environment', 'chair_471', 'chest_473'):
        if needle not in text:
            raise AssertionError({'missingSemanticLayerText': needle})


def assert_protected_sources() -> dict[str, str]:
    observed: dict[str, str] = {}
    for name, expected in PROTECTED_USD_HASHES.items():
        digest = hashlib.sha256((PROTECTED_USD_DIR / name).read_bytes()).hexdigest()
        observed[name] = digest
        if digest != expected:
            raise AssertionError({'protectedSourceChanged': name, 'expected': expected, 'observed': digest})
    return observed


def assert_semantic_state(state: dict) -> None:
    r17 = state['r17']
    outputs = r17.get('outputKeys') or []
    for key in REQUIRED_OUTPUT_KEYS:
        if key not in outputs:
            raise AssertionError({'missingOutputKey': key, 'outputs': outputs})
    id_map = state.get('robot_vision', {}).get('semanticIdMap') or {}
    joined = ' '.join(str(value) for value in id_map.values())
    if 'memory_cube' not in joined or 'retrieval_target' not in joined:
        raise AssertionError({'badSemanticIdMap': id_map})
    unique_ids = state.get('robot_vision', {}).get('semanticUniqueIds') or r17.get('semanticUniqueIds') or []
    if len(unique_ids) < 3:
        raise AssertionError({'tooFewSemanticIds': unique_ids})
    nonzero = state.get('robot_vision', {}).get('semanticNonzeroPixels') or r17.get('semanticNonzeroPixels') or 0
    if int(nonzero) <= 0:
        raise AssertionError({'semanticNonzeroPixels': nonzero})


def main() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    assert_semantics_layer()
    options = Options()
    options.binary_location = FIREFOX_BIN
    options.add_argument('-headless')
    options.set_preference('media.autoplay.default', 0)
    driver = webdriver.Firefox(service=Service(GECKODRIVER), options=options)
    result: dict[str, object] = {}
    try:
        driver.set_window_size(1280, 800)
        driver.get(URL)
        wait = WebDriverWait(driver, 60)
        video = wait.until(lambda d: d.find_element(By.ID, 'remote-video'))
        wait.until(lambda d: d.execute_script("const v=document.getElementById('remote-video'); return v && v.readyState >= 2 && v.videoWidth > 0 && v.videoHeight > 0;"))
        wait.until(lambda d: '/Root/Workshop/Cube' in d.find_element(By.CSS_SELECTOR, '.r17-signal-panel').text)
        wait.until(lambda d: all(not b.get_attribute('disabled') for b in d.find_elements(By.CSS_SELECTOR, '.r17-render-controls button')))
        video_tracks = driver.execute_script("const v=document.getElementById('remote-video'); return v.srcObject ? v.srcObject.getVideoTracks().length : 0;")

        click_button(driver, 'BEAUTY')
        beauty_state = wait_mode('BEAUTY')
        time.sleep(0.8)
        beauty_path, beauty = capture(driver, 'r17-beauty-mode.png', video)
        click_button(driver, 'SEMANTIC')
        sem_state = wait_mode('SEMANTIC')
        time.sleep(0.8)
        semantic_path, semantic = capture(driver, 'r17-semantic-mode.png', video)
        assert_semantic_state(sem_state)
        click_button(driver, 'BEAUTY')
        beauty2_state = wait_mode('BEAUTY')
        click_button(driver, 'SEMANTIC')
        sem2_state = wait_mode('SEMANTIC')
        click_button(driver, 'BEAUTY')
        final_state = wait_mode('BEAUTY')

        diff = ImageChops.difference(beauty['image'], semantic['image'])
        diff_mean = sum(ImageStat.Stat(diff).mean) / 3.0
        if semantic['variance'] < 1 or diff_mean < 3:
            raise AssertionError({'semanticViewNotDistinct': {'semanticMean': semantic['meanRgb'], 'semanticVariance': semantic['variance'], 'diffMean': diff_mean}})
        owner_counts = [s.get('renderer_owner_count') for s in (beauty_state, sem_state, beauty2_state, sem2_state, final_state)]
        if set(owner_counts) != {1}:
            raise AssertionError({'rendererOwnerCount': owner_counts})
        video_tracks_after = driver.execute_script("const v=document.getElementById('remote-video'); return v.srcObject ? v.srcObject.getVideoTracks().length : 0;")
        if video_tracks != 1 or video_tracks_after != 1:
            raise AssertionError({'videoTracks': [video_tracks, video_tracks_after]})
        protected = assert_protected_sources()
        result = {
            'beauty': {'state': beauty_state['r17']['renderMode'], 'artifact': str(beauty_path)},
            'semantic': {'state': sem_state['r17']['renderMode'], 'artifact': str(semantic_path), 'diffMean': diff_mean},
            'outputs': sem_state['r17']['outputKeys'],
            'semanticsLayer': sem_state['r17']['semanticsLayer'],
            'semanticIdMapEntries': len(sem_state['robot_vision'].get('semanticIdMap') or {}),
            'semanticUniqueIds': sem_state['robot_vision'].get('semanticUniqueIds'),
            'semanticNonzeroPixels': sem_state['robot_vision'].get('semanticNonzeroPixels'),
            'cubeSemanticClass': sem_state['robot_vision'].get('cubeSemanticClass'),
            'cubeSemanticLabel': sem_state['robot_vision'].get('cubeSemanticLabel'),
            'modeSwitches': ['BEAUTY', 'SEMANTIC', 'BEAUTY', 'SEMANTIC', 'BEAUTY'],
            'rendererOwnerCounts': owner_counts,
            'videoTracks': video_tracks_after,
            'protectedSourceHashes': protected,
            'finalMode': final_state['r17']['renderMode'],
        }
    finally:
        driver.quit()
    out = ARTIFACT_DIR / 'r17-robot-vision-smoke.json'
    out.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
