"""Roster page presentation. The upload rules are covered in test_roster.py.

Run from the repository root:

    PYTHONPATH=production python3 -m unittest production.tests.test_roster_page
"""

import json
import os
import shutil
import socket
import struct
import subprocess
import threading
import time
import unittest
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

from production.tests.test_roster import snapshot

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "ironkeep" / "static"
CHROME = shutil.which("google-chrome") or shutil.which("chromium")


class RosterPageTests(unittest.TestCase):
    def setUp(self):
        import ironkeep.main as site
        from ironkeep import db
        import production.tests.test_companion_phase1 as phase1

        site.templates.env.globals["asset"] = lambda path: "/static/" + path
        self.db = db
        self.fx = phase1.Phase1Tests()
        self.fx.setUp()
        self.fx.enable()
        self.fx.guild("11", "dutchchaos", self.fx.wow_settings(["9"]))
        db.upsert_guild("11", "dutchchaos", [], [], added_by="Ada", added_by_id="100")
        self.fx.member_roles[("100", "11")] = ["9"]
        self.fx.session("100")
        code, state = self.fx.allow("dutchchaos")
        self.token = self.fx.exchange(code, state)["access_token"]

    def tearDown(self):
        self.fx.doCleanups()

    def post(self, payload, slug="dutchchaos"):
        return self.fx.client.post(
            "/api/companion/guilds/%s/roster" % slug,
            content=json.dumps(payload),
            headers={"Authorization": "Bearer %s" % self.token, "Content-Type": "application/json"},
        )

    def open_page(self, slug="dutchchaos"):
        from unittest.mock import patch
        from ironkeep.discord_api import DiscordError

        with patch("ironkeep.discord_api.guild_member", side_effect=DiscordError(503, {})):
            return self.fx.client.get("/%s/roster" % slug, cookies={"ik_session": self.fx.website})

    def replace_members(self, members):
        conn = self.db.connect()
        try:
            conn.execute(
                "UPDATE roster_snapshots SET members_json = ? WHERE guild_id = ?",
                (json.dumps(members), "11"),
            )
            conn.commit()
        finally:
            conn.close()

    def test_the_three_roster_templates_match(self):
        production = (ROOT / "production/ironkeep/templates/roster.html").read_bytes()
        package = (ROOT / "ironkeep/templates/roster.html").read_bytes()
        installer = (ROOT / "deploy/companion-phase2/new/templates/roster.html").read_bytes()
        self.assertEqual(production, package)
        self.assertEqual(production, installer)

    def test_an_empty_guild_has_an_empty_state(self):
        page = self.open_page()
        self.assertEqual(page.status_code, 200, page.text)
        self.assertIn("No guild roster yet", page.text)
        self.assertNotIn("roster-table", page.text)
        self.assertNotIn("Player-", page.text)

    def test_the_page_lists_the_snapshot_without_guids(self):
        from ironkeep import roster

        posted = self.post(snapshot(1794011429, name="José", guild_name="Herberg"))
        self.assertEqual(posted.status_code, 200, posted.text)
        payload = snapshot(1794011429, name="Zara Quinn", guild_name="Otherberg")
        payload["members"][0]["guid"] = "Player-9"
        self.assertEqual(roster.store("22", payload, "b" * 64, now=1794011500), "stored")
        page = self.open_page()
        self.assertEqual(page.status_code, 200, page.text)
        captured = datetime.fromtimestamp(1794011429, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        self.assertIn("José", page.text)
        self.assertIn("Herberg", page.text)
        self.assertIn(captured, page.text)
        self.assertIn(">WoW guild<", page.text)
        self.assertIn(">Members<", page.text)
        self.assertIn(">Captured<", page.text)
        self.assertIn(">Received<", page.text)
        self.assertIn(" UTC", page.text)
        self.assertIn(">Character<", page.text)
        self.assertIn(">Class<", page.text)
        self.assertIn(">Level<", page.text)
        self.assertIn(">Guild rank<", page.text)
        self.assertNotIn("Zara Quinn", page.text)
        self.assertNotIn("Otherberg", page.text)
        self.assertNotIn("Player-1", page.text)
        self.assertNotIn("Player-9", page.text)
        self.assertNotIn("online", page.text.lower())
        self.assertNotIn("offline", page.text.lower())

    def test_names_and_ranks_are_escaped_and_broken_rows_are_skipped(self):
        self.assertEqual(self.post(snapshot(1794011429)).status_code, 200)
        self.replace_members([
            {
                "guid": "Player-1",
                "name": "Ada <Smith>",
                "level": 70,
                "classToken": "MAGE",
                "className": "Magiër",
                "rankName": 'Raider & "Core"',
                "online": True,
            },
            "nope",
            {"name": "   ", "level": True, "className": "", "rankName": None, "classToken": "MAGE"},
            {
                "name": "Bea",
                "level": 10,
                "classToken": "PEASANT",
                "className": "Peasant",
                "rankName": "Recruit",
            },
        ])
        page = self.open_page()
        self.assertEqual(page.status_code, 200, page.text)
        self.assertIn("Ada &lt;Smith&gt;", page.text)
        self.assertNotIn("Ada <Smith>", page.text)
        self.assertIn("Raider &amp;", page.text)
        self.assertIn("Magiër", page.text)
        self.assertIn("--swatch: #3FC7EB", page.text)
        self.assertIn("Peasant", page.text)
        self.assertNotIn("PEASANT", page.text)
        self.assertNotIn("nope", page.text)
        self.assertNotIn("Player-1", page.text)
        self.assertNotIn("online", page.text.lower())
        self.assertEqual(page.text.count("data-character="), 3)
        self.assertNotIn('data-level="True"', page.text)
        self.assertNotIn('data-level="1"', page.text)
        self.assertIn(">All classes<", page.text)
        self.assertIn(">Magiër<", page.text)
        self.assertIn(">Recruit<", page.text)

    def test_a_snapshot_without_a_character_list_stays_on_the_page(self):
        self.assertEqual(self.post(snapshot(1794011429)).status_code, 200)
        self.replace_members({"bad": True})
        broken = self.open_page()
        self.assertEqual(broken.status_code, 200, broken.text)
        self.assertIn("This roster cannot be shown", broken.text)
        self.assertIn("Herberg", broken.text)
        self.assertNotIn("roster-table", broken.text)
        self.replace_members([])
        empty = self.open_page()
        self.assertEqual(empty.status_code, 200, empty.text)
        self.assertIn("No characters in this roster", empty.text)
        self.assertIn(">0<", empty.text)

    def test_two_hundred_thirty_eight_members_render(self):
        classes = [
            ("WARRIOR", "Warrior", "#C69B6D"),
            ("MAGE", "Magiër", "#3FC7EB"),
            ("DRUID", "Druïde", "#FF7C0A"),
            ("HUNTER", "Hunter", "#AAD372"),
        ]
        ranks = ["Guild Master", "Officer", "Member", "Рыцарь"]
        names = ["Łukasz", "José", "Иван", "李明"]
        members = []
        for index in range(238):
            token, class_name, _color = classes[index % len(classes)]
            name = names[index] if index < len(names) else "Member %s" % (index + 1)
            members.append({
                "guid": "Player-%s" % (index + 1),
                "name": name,
                "level": (index % 70) + 1,
                "classToken": token,
                "className": class_name,
                "rankName": ranks[index % len(ranks)],
            })
        payload = snapshot(1794011429)
        payload["members"] = members
        posted = self.post(payload)
        self.assertEqual(posted.status_code, 200, posted.text)
        page = self.open_page()
        self.assertEqual(page.status_code, 200, page.text)
        self.assertEqual(page.text.count("data-character="), 238)
        self.assertIn(">238<", page.text)
        for name in names:
            self.assertIn(name, page.text)
        self.assertIn("Magiër", page.text)
        self.assertIn("Druïde", page.text)
        self.assertIn("Рыцарь", page.text)
        self.assertIn("--swatch: #C69B6D", page.text)
        self.assertNotIn("Player-", page.text)
        self.assertIn(">All classes<", page.text)
        self.assertIn(">All ranks<", page.text)
        self.assertIn('id="roster-empty" hidden', page.text)
        self.assertIn("No characters match your current search or filters.", page.text)
        self.assertIn('id="roster-clear" hidden', page.text)
        self.assertIn('data-label="Guild rank"', page.text)
        self.assertIn("th[data-sort]:focus-visible", page.text)
        self.assertIn('id="roster-match" hidden', page.text)


class RosterBrowserTests(unittest.TestCase):
    setUp = RosterPageTests.setUp
    tearDown = RosterPageTests.tearDown
    post = RosterPageTests.post
    open_page = RosterPageTests.open_page

    @unittest.skipUnless(CHROME, "chrome is not installed")
    def test_search_filter_sort_and_layout(self):
        members = [
            ("Player-a", "Ada Smith", 70, "WARRIOR", "Warrior", "Member"),
            ("Player-b", "José", 10, "MAGE", "Magiër", "Officier"),
            ("Player-c", "Łukasz", 60, "DRUID", "Druïde", "Member"),
            ("Player-d", "Иван", 45, "HUNTER", "Hunter", "Рыцарь"),
            ("Player-e", "李明", 80, "PRIEST", "Priest", "Officier"),
        ]
        payload = snapshot(1794011429)
        payload["members"] = [
            {
                "guid": guid,
                "name": name,
                "level": level,
                "classToken": token,
                "className": class_name,
                "rankName": rank,
            }
            for guid, name, level, token, class_name, rank in members
        ]
        self.assertEqual(self.post(payload).status_code, 200)
        filled = self.open_page()
        self.assertEqual(filled.status_code, 200, filled.text)
        browser = ChromeSession()
        try:
            browser.start()
            browser.serve("filled", filled.text)
            browser.serve("empty", self._empty_page())
            browser.open("filled", 1280, 800)
            self.assertEqual(
                set(browser.eval("Array.from(document.querySelectorAll('#roster-table tbody tr')).map(row => row.dataset.character)")),
                {"Ada Smith", "José", "Łukasz", "Иван", "李明"},
            )
            self.assertEqual(browser.eval(_sorted_as("character")), True)
            self.assertEqual(browser.eval("document.body.innerText.includes('Player-')"), False)
            browser.eval("document.getElementById('roster-search').value = 'JOSÉ'; document.getElementById('roster-search').dispatchEvent(new Event('input'))")
            self.assertEqual(browser.eval("Array.from(document.querySelectorAll('#roster-table tbody tr')).filter(row => !row.hidden).map(row => row.dataset.character)"), ["José"])
            self.assertEqual(browser.eval("document.getElementById('roster-match').textContent"), "1 of 5 characters")
            browser.eval("document.getElementById('roster-search').value = 'jose'; document.getElementById('roster-search').dispatchEvent(new Event('input'))")
            self.assertEqual(browser.eval("document.getElementById('roster-match').textContent"), "0 of 5 characters")
            self.assertEqual(browser.eval("document.getElementById('roster-empty').hidden"), False)
            browser.screenshot("roster-no-match.png")
            browser.eval("document.getElementById('roster-search').value = 'łuk'; document.getElementById('roster-search').dispatchEvent(new Event('input'))")
            self.assertEqual(browser.eval("Array.from(document.querySelectorAll('#roster-table tbody tr')).filter(row => !row.hidden).map(row => row.dataset.character)"), ["Łukasz"])
            browser.eval("document.getElementById('roster-search').value = ''; document.getElementById('roster-search').dispatchEvent(new Event('input'))")
            self.assertEqual(browser.eval("document.getElementById('roster-match').hidden"), True)
            browser.eval("document.getElementById('roster-class').value = 'Magiër'; document.getElementById('roster-class').dispatchEvent(new Event('change'))")
            self.assertEqual(browser.eval("Array.from(document.querySelectorAll('#roster-table tbody tr')).filter(row => !row.hidden).map(row => row.dataset.character)"), ["José"])
            browser.eval("document.getElementById('roster-rank').value = 'Member'; document.getElementById('roster-rank').dispatchEvent(new Event('change'))")
            self.assertEqual(browser.eval("document.getElementById('roster-match').textContent"), "0 of 5 characters")
            self.assertEqual(browser.eval("document.getElementById('roster-empty').textContent.trim()"), "No characters match your current search or filters.")
            self.assertEqual(browser.eval("document.getElementById('roster-clear').hidden"), False)
            browser.eval("document.getElementById('roster-clear').click()")
            self.assertEqual(browser.eval("document.getElementById('roster-search').value"), "")
            self.assertEqual(browser.eval("document.getElementById('roster-class').value"), "")
            self.assertEqual(browser.eval("document.getElementById('roster-rank').value"), "")
            self.assertEqual(browser.eval("document.getElementById('roster-clear').hidden"), True)
            self.assertEqual(browser.eval("document.getElementById('roster-match').hidden"), True)
            browser.eval("document.getElementById('roster-class').value = ''; document.getElementById('roster-rank').value = 'Officier'; document.getElementById('roster-rank').dispatchEvent(new Event('change'))")
            self.assertEqual(
                set(browser.eval("Array.from(document.querySelectorAll('#roster-table tbody tr')).filter(row => !row.hidden).map(row => row.dataset.character)")),
                {"José", "李明"},
            )
            browser.eval("document.getElementById('roster-rank').value = ''; document.getElementById('roster-rank').dispatchEvent(new Event('change'))")
            browser.eval("document.querySelector('th[data-sort=\"level\"]').click()")
            self.assertEqual(
                browser.eval("Array.from(document.querySelectorAll('#roster-table tbody tr')).map(row => Number(row.dataset.level))"),
                [10, 45, 60, 70, 80],
            )
            browser.eval("document.querySelector('th[data-sort=\"level\"]').click()")
            self.assertEqual(
                browser.eval("Array.from(document.querySelectorAll('#roster-table tbody tr')).map(row => Number(row.dataset.level))"),
                [80, 70, 60, 45, 10],
            )
            browser.eval("document.querySelector('th[data-sort=\"className\"]').click()")
            self.assertEqual(browser.eval(_sorted_as("className")), True)
            browser.eval("document.querySelector('th[data-sort=\"rankName\"]').click()")
            first = browser.eval("Array.from(document.querySelectorAll('#roster-table tbody tr')).map(row => row.dataset.rankName)")
            browser.eval("document.querySelector('th[data-sort=\"rankName\"]').click()")
            second = browser.eval("Array.from(document.querySelectorAll('#roster-table tbody tr')).map(row => row.dataset.rankName)")
            self.assertEqual(first, list(reversed(second)))
            browser.eval("document.querySelector('th[data-sort=\"character\"]').click()")
            browser.resize(1280, 800)
            browser.screenshot("roster-desktop.png")
            wide = browser.eval("document.getElementById('roster-table').getBoundingClientRect().width")
            browser.resize(390, 844)
            time.sleep(0.35)
            self.assertEqual(browser.eval("window.innerWidth"), 390)
            self.assertLessEqual(browser.eval("document.querySelector('.sidebar').getBoundingClientRect().right"), 0)
            self.assertLessEqual(browser.eval("document.documentElement.scrollWidth"), browser.eval("document.documentElement.clientWidth"))
            self.assertLessEqual(browser.eval("document.querySelector('#roster-table td[data-label=\"Level\"]').getBoundingClientRect().right"), 390)
            self.assertLessEqual(browser.eval("document.querySelector('#roster-table td[data-label=\"Guild rank\"]').getBoundingClientRect().right"), 390)
            browser.screenshot("roster-narrow.png")
            browser.resize(320, 720)
            time.sleep(0.2)
            self.assertLessEqual(browser.eval("document.documentElement.scrollWidth"), browser.eval("Math.max(document.documentElement.clientWidth, 320)"))
            self.assertLessEqual(browser.eval("document.querySelector('#roster-table td[data-label=\"Guild rank\"]').getBoundingClientRect().right"), 321)
            self.assertGreater(wide, 600)
            many = snapshot(1794013000)
            many["members"] = [
                {
                    "guid": "Player-%s" % (index + 1),
                    "name": "Member %s" % (index + 1),
                    "level": (index % 70) + 1,
                    "classToken": "WARRIOR",
                    "className": "Warrior",
                    "rankName": "Member",
                }
                for index in range(238)
            ]
            many["members"][0]["name"] = "Łukasz"
            posted = self.post(many)
            self.assertEqual(posted.status_code, 200, posted.text)
            browser.serve("many", self.open_page().text)
            browser.open("many", 1280, 800)
            self.assertEqual(browser.eval("document.body.innerText.includes('238')"), True)
            self.assertEqual(browser.eval("document.querySelectorAll('#roster-table tbody tr').length"), 238)
            scrolled = json.loads(browser.eval(
                "(() => { const wrap = document.querySelector('.table-wrap'); const head = document.querySelector('#roster-table thead th'); const search = document.getElementById('roster-search'); const before = search.getBoundingClientRect().top; wrap.scrollTop = 480; const headTop = head.getBoundingClientRect().top; const wrapTop = wrap.getBoundingClientRect().top; return JSON.stringify({scroll: wrap.scrollTop, stuck: Math.abs(headTop - wrapTop) < 3, filterStill: Math.abs(search.getBoundingClientRect().top - before) < 2, page: document.scrollingElement.scrollTop}); })()"
            ))
            self.assertGreater(scrolled["scroll"], 100)
            self.assertEqual(scrolled["stuck"], True)
            self.assertEqual(scrolled["filterStill"], True)
            self.assertEqual(scrolled["page"], 0)
            browser.eval("document.getElementById('roster-rank').focus()")
            browser.call("Input.dispatchKeyEvent", type="keyDown", key="Tab", code="Tab", windowsVirtualKeyCode=9, nativeVirtualKeyCode=9)
            browser.call("Input.dispatchKeyEvent", type="keyUp", key="Tab", code="Tab", windowsVirtualKeyCode=9, nativeVirtualKeyCode=9)
            focused = json.loads(browser.eval(
                "(() => { const th = document.activeElement; const style = getComputedStyle(th); const before = th.getAttribute('aria-sort'); th.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true})); return JSON.stringify({id: th.id || '', sort: th.dataset.sort || '', outline: style.outlineStyle, width: style.outlineWidth, visible: th.matches(':focus-visible'), before: before, after: th.getAttribute('aria-sort')}); })()"
            ))
            self.assertEqual(focused["sort"], "character", focused)
            self.assertEqual(focused["visible"], True, focused)
            self.assertEqual(focused["outline"], "solid", focused)
            self.assertNotEqual(focused["before"], focused["after"], focused)
            browser.screenshot("roster-many.png")
            browser.open("empty", 1280, 800)
            self.assertEqual(browser.eval("document.body.innerText.includes('No guild roster yet')"), True)
            self.assertEqual(browser.eval("document.getElementById('roster-table')"), None)
            browser.screenshot("roster-empty.png")
        finally:
            browser.close()

    def _empty_page(self):
        conn = self.db.connect()
        try:
            conn.execute("DELETE FROM roster_snapshots WHERE guild_id = ?", ("11",))
            conn.commit()
        finally:
            conn.close()
        page = self.open_page()
        self.assertEqual(page.status_code, 200, page.text)
        return page.text


def _sorted_as(key):
    attr = {"character": "character", "className": "className", "rankName": "rankName"}[key]
    return (
        "(() => {"
        " const values = Array.from(document.querySelectorAll('#roster-table tbody tr')).map(row => row.dataset.%s);"
        " const expected = values.slice().sort((a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: 'accent' }));"
        " return JSON.stringify(values) === JSON.stringify(expected);"
        "})()"
    ) % attr


class ChromeSession:
    def __init__(self):
        self.httpd = None
        self.thread = None
        self.proc = None
        self.sock = None
        self.call_id = 0
        self.directory = None

    def start(self):
        self.directory = Path("/tmp/roster-ui-%s" % os.getpid())
        if self.directory.exists():
            shutil.rmtree(self.directory)
        self.directory.mkdir()
        handler = self._handler()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.httpd.server_address[1]
        debug = _free_port()
        profile = self.directory / "profile"
        self.proc = subprocess.Popen(
            [
                CHROME,
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--no-first-run",
                "--disable-extensions",
                "--remote-debugging-port=%s" % debug,
                "--lang=en-US",
                "--user-data-dir=%s" % profile,
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        tabs = _wait_json("http://127.0.0.1:%s/json/list" % debug)
        page = next(tab for tab in tabs if tab.get("type") == "page")
        path = page["webSocketDebuggerUrl"].split("/", 3)[3]
        self.sock = _ws_connect("127.0.0.1", debug, "/" + path)
        self.call("Page.enable")
        self.call("Runtime.enable")

    def serve(self, name, html):
        (self.directory / ("%s.html" % name)).write_text(html, encoding="utf-8")

    def open(self, name, width, height):
        self.call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=1, mobile=width < 700)
        self.call("Page.navigate", url="http://127.0.0.1:%s/%s.html" % (self.port, name))
        deadline = time.time() + 10
        while time.time() < deadline:
            state = self.eval("document.readyState")
            if state == "complete" and self.eval("document.getElementById('roster-table') !== undefined"):
                return
            time.sleep(0.05)
        raise AssertionError("page did not load")

    def resize(self, width, height):
        self.call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=1, mobile=width < 700)

    def eval(self, expression):
        result = self.call("Runtime.evaluate", expression=expression, returnByValue=True)
        details = result.get("exceptionDetails")
        if details:
            raise AssertionError(json.dumps(details))
        return result["result"].get("value")

    def screenshot(self, name):
        folder = Path("/opt/cursor/artifacts")
        if not folder.exists():
            return
        payload = self.call("Page.captureScreenshot", format="png")
        import base64
        (folder / name).write_bytes(base64.b64decode(payload["data"]))

    def call(self, method, **params):
        self.call_id += 1
        ident = self.call_id
        _ws_send(self.sock, json.dumps({"id": ident, "method": method, "params": params}))
        deadline = time.time() + 10
        while time.time() < deadline:
            message = json.loads(_ws_recv(self.sock))
            if message.get("id") == ident:
                if "error" in message:
                    raise AssertionError(message["error"])
                return message.get("result", {})
        raise AssertionError("no reply for %s" % method)

    def close(self):
        if self.sock is not None:
            self.sock.close()
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
        if self.directory is not None and self.directory.exists():
            shutil.rmtree(self.directory, ignore_errors=True)

    def _handler(self):
        directory = self.directory

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                path = self.path.split("?", 1)[0]
                if path.startswith("/static/"):
                    target = STATIC / path[len("/static/"):]
                    if not target.is_file() or STATIC not in target.resolve().parents:
                        self.send_error(404)
                        return
                    body = target.read_bytes()
                    kind = "text/css" if target.suffix == ".css" else "application/javascript" if target.suffix == ".js" else "application/octet-stream"
                else:
                    target = directory / path.lstrip("/")
                    if not target.is_file():
                        self.send_error(404)
                        return
                    body = target.read_bytes()
                    kind = "text/html; charset=utf-8"
                self.send_response(200)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, fmt, *args):
                return

        return Handler


def _free_port():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def _wait_json(url):
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            with urlopen(url, timeout=1) as response:
                return json.load(response)
        except OSError:
            time.sleep(0.1)
    raise AssertionError("chrome did not open a debugging port")


def _ws_connect(host, port, path):
    sock = socket.create_connection((host, port))
    key = "dGhlIHNhbXBsZSBub25jZQ=="
    sock.sendall(
        (
            "GET %s HTTP/1.1\r\nHost: %s:%s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
            "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % (path, host, port, key)
        ).encode()
    )
    data = b""
    while b"\r\n\r\n" not in data:
        data += sock.recv(4096)
    if b" 101 " not in data.split(b"\r\n", 1)[0]:
        raise AssertionError(data[:200])
    return sock


def _ws_send(sock, text):
    payload = text.encode()
    mask = os.urandom(4)
    header = bytearray([0x81])
    length = len(payload)
    if length < 126:
        header.append(0x80 | length)
    elif length < 65536:
        header.append(0x80 | 126)
        header.extend(struct.pack(">H", length))
    else:
        header.append(0x80 | 127)
        header.extend(struct.pack(">Q", length))
    header.extend(mask)
    sock.sendall(bytes(header) + bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload)))


def _ws_recv(sock):
    chunks = []
    while True:
        fin, opcode, payload = _ws_frame(sock)
        if opcode == 8:
            raise AssertionError("chrome closed the socket")
        if opcode == 9:
            _ws_send_pong(sock, payload)
            continue
        if opcode in (0, 1):
            chunks.append(payload)
        if fin and opcode != 9:
            return b"".join(chunks).decode()


def _ws_frame(sock):
    def read(count):
        buf = b""
        while len(buf) < count:
            chunk = sock.recv(count - len(buf))
            if not chunk:
                raise AssertionError("chrome socket closed")
            buf += chunk
        return buf

    first, second = read(2)
    length = second & 0x7F
    if length == 126:
        length = struct.unpack(">H", read(2))[0]
    elif length == 127:
        length = struct.unpack(">Q", read(8))[0]
    if second & 0x80:
        mask = read(4)
        payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(read(length)))
    else:
        payload = read(length)
    return bool(first & 0x80), first & 0x0F, payload


def _ws_send_pong(sock, payload):
    header = bytearray([0x8A])
    mask = os.urandom(4)
    header.append(0x80 | len(payload))
    header.extend(mask)
    sock.sendall(bytes(header) + bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload)))


if __name__ == "__main__":
    unittest.main()
