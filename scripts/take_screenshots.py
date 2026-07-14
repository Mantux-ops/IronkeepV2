"""
Visual validation screenshot script for Phase 12.2b.

Usage:
    python scripts/take_screenshots.py
"""
from __future__ import annotations
import os, sys, tempfile, time, uuid, threading
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import uvicorn
from playwright.sync_api import sync_playwright
from app import database
from app.main import app
from tests.conftest import make_user, make_workspace

# ── DB + workspace setup ────────────────────────────────────────────────────

DB_PATH = tempfile.mktemp(suffix=".db")
database.configure(DB_PATH)
database.init_schema()

owner = make_user("VisualValidator")
SLUG  = "visual-" + uuid.uuid4().hex[:6]
ws    = make_workspace(name="Visual WS", slug=SLUG, owner_user_id=owner["id"])
OWNER = owner["display_name"]

# ── Start server ─────────────────────────────────────────────────────────────

PORT = 19765
config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="error")
server = uvicorn.Server(config)

def _run():
    server.run()

thread = threading.Thread(target=_run, daemon=True)
thread.start()

# Wait for server
import urllib.request
for _ in range(30):
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health")
        break
    except Exception:
        time.sleep(0.3)

BASE = f"http://127.0.0.1:{PORT}"
EDITOR = f"{BASE}/workspaces/{SLUG}/builds/editor"
OUT = "screenshots"
os.makedirs(OUT, exist_ok=True)

# ── Screenshots ───────────────────────────────────────────────────────────────

with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx     = browser.new_context(viewport={"width": 1280, "height": 800})
    page    = ctx.new_page()

    def login():
        page.goto(f"{BASE}/login")
        page.fill('input[name="display_name"]', OWNER)
        page.click('input[type="submit"]')
        page.wait_for_url(f"{BASE}/workspaces**", timeout=5000)

    # 1. Empty editor
    login()
    page.goto(EDITOR)
    page.wait_for_selector('.vbe-slot', timeout=5000)
    page.screenshot(path=f"{OUT}/1_empty_editor_1280.png")
    print("Screenshot 1: empty editor (1280px)")

    # 2. Main-hand picker open
    page.click('#vbe-slot-main_hand')
    page.wait_for_selector('.vbe-item-card', timeout=8000)
    page.screenshot(path=f"{OUT}/2_main_hand_picker.png")
    print("Screenshot 2: main-hand picker open")

    # 3. Claymore search results
    page.fill('#vbe-search', 'Claymore')
    page.wait_for_timeout(400)
    page.screenshot(path=f"{OUT}/3_claymore_search.png")
    print("Screenshot 3: Claymore search results")

    # 4. T8.3 Claymore selected
    page.click('[data-tier="7"]')
    page.wait_for_timeout(100)
    for e in ['0', '1', '2']:
        page.click(f'[data-ench="{e}"]')
        page.wait_for_timeout(80)
    page.wait_for_selector('.vbe-item-card', timeout=4000)
    page.locator('.vbe-item-card').first.click()
    page.wait_for_selector('#vbe-slot-main_hand.vbe-slot--filled', timeout=3000)
    page.screenshot(path=f"{OUT}/4_t8_3_claymore_selected.png")
    print("Screenshot 4: T8.3 Claymore selected, off-hand disabled")

    # 5. Complete build (fill remaining slots)
    for slot in ['head', 'chest', 'shoes', 'cape', 'bag', 'mount', 'food', 'potion']:
        page.click(f'#vbe-slot-{slot}')
        page.wait_for_selector('.vbe-item-card', timeout=8000)
        page.locator('.vbe-item-card').first.click()
        page.wait_for_selector(f'#vbe-slot-{slot}.vbe-slot--filled', timeout=3000)
    page.screenshot(path=f"{OUT}/5_complete_build.png")
    print("Screenshot 5: complete build")

    # 6. Empty-results state
    page.click('#vbe-slot-chest')
    page.wait_for_selector('.vbe-item-card', timeout=8000)
    page.fill('#vbe-search', 'xyznonexistentitem999abc')
    page.wait_for_timeout(400)
    page.screenshot(path=f"{OUT}/6_empty_results.png")
    print("Screenshot 6: empty results state")
    page.keyboard.press('Escape')
    page.wait_for_timeout(300)

    # 7. Render-limit notice
    page.click('#vbe-slot-main_hand')
    page.wait_for_selector('.vbe-item-card', timeout=8000)
    page.screenshot(path=f"{OUT}/7_render_limit.png")
    print("Screenshot 7: render-limit notice (main_hand 1096 items)")
    page.keyboard.press('Escape')
    page.wait_for_timeout(300)

    # 8. Narrow viewport (390px)
    ctx2  = browser.new_context(viewport={"width": 390, "height": 844})
    page2 = ctx2.new_page()
    page2.goto(f"{BASE}/login")
    page2.fill('input[name="display_name"]', OWNER)
    page2.click('input[type="submit"]')
    page2.wait_for_url(f"{BASE}/workspaces**", timeout=5000)
    page2.goto(EDITOR)
    page2.wait_for_selector('.vbe-slot', timeout=5000)
    page2.screenshot(path=f"{OUT}/8_narrow_390.png")
    print("Screenshot 8: narrow viewport 390px")

    page2.click('#vbe-slot-head')
    page2.wait_for_selector('.vbe-item-card', timeout=8000)
    page2.screenshot(path=f"{OUT}/9_narrow_390_picker.png")
    print("Screenshot 9: narrow viewport 390px with picker open")

    ctx2.close()

    # 9. Tablet viewport (768px)
    ctx3  = browser.new_context(viewport={"width": 768, "height": 1024})
    page3 = ctx3.new_page()
    page3.goto(f"{BASE}/login")
    page3.fill('input[name="display_name"]', OWNER)
    page3.click('input[type="submit"]')
    page3.wait_for_url(f"{BASE}/workspaces**", timeout=5000)
    page3.goto(EDITOR)
    page3.wait_for_selector('.vbe-slot', timeout=5000)
    page3.screenshot(path=f"{OUT}/10_tablet_768.png")
    print("Screenshot 10: tablet viewport 768px")
    ctx3.close()

    browser.close()

server.should_exit = True
print(f"\nAll screenshots saved to ./{OUT}/")
