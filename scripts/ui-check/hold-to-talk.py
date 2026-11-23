#!/usr/bin/env python3
"""
Browser check of the "hold to talk" gestures (Space AND click-and-hold) on the running web app.

    uv run --with websockets scripts/ui-check/hold-to-talk.py            # needs the stack up (make up) on :5173
    uv run --with websockets scripts/ui-check/hold-to-talk.py --show     # headed Edge instead of headless

It starts its OWN throw-away Edge (temporary profile, fake microphone, no relation with your browsers) and drives it
through the Chrome DevTools Protocol with REAL input events (Input.dispatchKeyEvent / dispatchMouseEvent).
No AI quota is spent: the page's WebSocket to /ai/voice* and its POST /ai/command are replaced by recorders, so
what we assert is exactly what the page WOULD send (audio_start / audio_end / audio_cancel …). The ERP is only read.
Exit code 0 = every case passed.
"""

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request

import websockets

PORT = 9333

STUB = r"""
(() => {
  window.__log = [];
  const Real = window.WebSocket;
  class Fake {
    constructor(url) {
      this.url = url; this.readyState = 0; this.onopen = this.onmessage = this.onclose = this.onerror = null; this.bufferedAmount = 0;
      window.__log.push({ t: "ws-open", url });
      setTimeout(() => { this.readyState = 1; this.onopen && this.onopen({}); }, 0);
    }
    send(d) {
      const s = typeof d === "string";
      window.__log.push({ t: "ws-send", url: this.url, type: s ? JSON.parse(d).type : "binary", mime: s ? JSON.parse(d).mime : undefined });
      if (s && JSON.parse(d).type === "start")
        setTimeout(() => this.onmessage && this.onmessage({ data: JSON.stringify({ type: "ready", sessionId: "fake", stt: "fake", tts: "fake", llm: "fake" }) }), 0);
    }
    close() { this.readyState = 3; window.__log.push({ t: "ws-close", url: this.url }); this.onclose && this.onclose({}); }
    addEventListener() {} removeEventListener() {}
  }
  const W = function (url, p) { return /\/ai\/voice/.test(String(url)) ? new Fake(String(url)) : new Real(url, p); };
  Object.assign(W, { CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3 });
  W.prototype = Real.prototype;
  window.WebSocket = W;
  const realFetch = window.fetch.bind(window);
  window.fetch = (input, init) => {
    const url = typeof input === "string" ? input : input.url;
    if (/\/ai\/command/.test(url) && (init?.method || "GET") === "POST") {
      window.__log.push({ t: "fetch-command" });
      return Promise.resolve(new Response('{"error":{"message":"stubbed by the UI check"}}', { status: 500, headers: { "content-type": "application/json" } }));
    }
    return realFetch(input, init);
  };
})();
"""


class Page:
    def __init__(self, ws):
        self.ws, self.n, self.pending = ws, 0, {}
        self.reader = asyncio.create_task(self._read())

    async def _read(self):
        async for raw in self.ws:
            m = json.loads(raw)
            if "id" in m and m["id"] in self.pending:
                self.pending.pop(m["id"]).set_result(m)

    async def call(self, method, **params):
        self.n += 1
        fut = asyncio.get_running_loop().create_future()
        self.pending[self.n] = fut
        await self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        res = await asyncio.wait_for(fut, 30)
        if "error" in res:
            raise RuntimeError(f"{method}: {res['error']}")
        return res.get("result", {})

    async def js(self, expr):
        r = await self.call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        return r.get("result", {}).get("value")

    async def goto(self, url):
        await self.call("Page.navigate", url=url)
        await asyncio.sleep(1.5)
        await self.js("new Promise(r => (document.readyState === 'complete' ? r() : addEventListener('load', r)))")

    async def key(self, kind, code="Space", key=" ", vk=32, modifiers=0, repeat=False):
        await self.call(
            "Input.dispatchKeyEvent", type=kind, code=code, key=key, windowsVirtualKeyCode=vk, modifiers=modifiers,
            autoRepeat=repeat, **({"text": key} if kind == "keyDown" and key == " " else {}),
        )

    async def center(self, selector):
        r = await self.js(f"(() => {{ const e = document.querySelector({json.dumps(selector)}); if (!e) return null; const b = e.getBoundingClientRect(); return [b.x + b.width / 2, b.y + b.height / 2]; }})()")
        if not r:
            raise RuntimeError(f"no element {selector}")
        return r

    async def mouse(self, kind, x, y, down=False):
        """down=True: the left button is held during a mouseMoved (a drag), as with a real mouse."""
        await self.call(
            "Input.dispatchMouseEvent", type=kind, x=x, y=y, button="left" if kind != "mouseMoved" or down else "none",
            buttons=1 if kind == "mousePressed" or down else 0, clickCount=1 if kind != "mouseMoved" else 0,
        )

    async def log(self):
        return await self.js("window.__log") or []

    async def clear(self):
        await self.js("window.__log = []")

    async def sent(self, url_part):
        """Types of the messages the page sent to sockets whose url contains url_part (binary frames collapsed)."""
        out = []
        for e in await self.log():
            if e["t"] == "ws-send" and url_part in e["url"]:
                if e["type"] == "binary" and out and out[-1] == "binary":
                    continue
                out.append(e["type"])
        return out


def start_edge(show: bool):
    exe = shutil.which("microsoft-edge") or shutil.which("google-chrome") or shutil.which("chromium")
    if not exe:
        sys.exit("no Edge / Chrome / Chromium found")
    prof = tempfile.mkdtemp(prefix="ui-check-")
    args = [
        exe, f"--remote-debugging-port={PORT}", f"--user-data-dir={prof}", "--no-first-run", "--no-default-browser-check",
        "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", "--window-size=1440,900", "--disable-gpu", "about:blank",
    ]
    if not show:
        args.insert(1, "--headless=new")
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL), prof


async def wait_page():
    for _ in range(60):
        try:
            tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list", timeout=2))
            tab = next((t for t in tabs if t["type"] == "page"), None)
            if tab:
                return tab["webSocketDebuggerUrl"]
        except Exception:
            pass
        await asyncio.sleep(0.5)
    sys.exit("Edge did not start")


results: list[tuple[str, bool, str]] = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"  {'✅' if ok else '❌'} {name}" + ("" if ok else f"   → {detail}"), flush=True)


async def hold_space(p: Page, ms=600, repeats=3, modifiers=0):
    await p.key("keyDown", modifiers=modifiers)
    for _ in range(repeats):
        await asyncio.sleep(ms / 1000 / (repeats + 1))
        await p.key("keyDown", repeat=True, modifiers=modifiers)
    await asyncio.sleep(ms / 1000 / (repeats + 1))
    await p.key("keyUp", modifiers=modifiers)
    await asyncio.sleep(0.6)


async def hold_click(p: Page, selector, ms=600, release_at=None):
    x, y = await p.center(selector)
    await p.mouse("mouseMoved", x, y)
    await p.mouse("mousePressed", x, y)
    await asyncio.sleep(ms / 1000)
    rx, ry = release_at or (x, y)
    if release_at:
        await p.mouse("mouseMoved", rx, ry, down=True)
    await p.mouse("mouseReleased", rx, ry)
    await asyncio.sleep(0.6)


async def wait_ready(p: Page, url_part="/ai/voice"):
    for _ in range(40):
        if any(e["t"] == "ws-send" and e["type"] == "start" and url_part in e["url"] for e in await p.log()):
            return
        await asyncio.sleep(0.25)


async def run(base: str, show: bool, shot: str | None) -> int:
    proc, prof = start_edge(show)
    try:
        p = Page(await websockets.connect(await wait_page(), max_size=None))
        await p.call("Page.enable")
        await p.call("Runtime.enable")
        await p.call("Page.addScriptToEvaluateOnNewDocument", source=STUB)
        await p.call("Emulation.setFocusEmulationEnabled", enabled=True)

        STARTED = ["audio_start", "binary", "audio_end"]

        # ── anywhere in the app (here the orders list): the header "Voix" button = one-shot command ──
        print("Global command (header button, page /orders)")
        await p.goto(f"{base}/orders")
        if shot:
            png = (await p.call("Page.captureScreenshot", format="png", clip={"x": 760, "y": 0, "width": 680, "height": 60, "scale": 2})).get("data", "")
            open(shot, "wb").write(__import__("base64").b64decode(png))
        BTN = "button[data-hold-to-talk='command']"
        await p.clear()
        await hold_space(p)
        got = await p.sent("/voice/command")
        check("Space (hold, with key auto-repeat) starts and stops ONE command recording", got == ["audio_start", "binary", "audio_end"], got)

        await p.clear()
        await hold_click(p, BTN)
        got = await p.sent("/voice/command")
        check("click-and-hold on the button starts and stops ONE command recording", got == STARTED, got)

        await p.clear()
        await hold_click(p, BTN, release_at=(20, 20))
        got = await p.sent("/voice/command")
        check("release OUTSIDE the button still stops (pointer capture)", got == STARTED, got)

        await p.clear()
        await hold_click(p, BTN, ms=60)
        got = await p.sent("/voice/command")
        check("a simple click (tap) leaves no stub recording (no audio_end sent)", "audio_end" not in got, got)

        # (a real hold, not a tap: a tap opens the typed-command HUD, which rightly takes the focus for typing)
        await hold_click(p, BTN)  # the mouse leaves keyboard focus on the button
        await p.clear()
        await hold_space(p)
        got = await p.sent("/voice/command")
        check("Space while the talk button has focus: exactly ONE recording (no double fire)", got.count("audio_start") == 1 and got[-1:] == ["audio_end"], got)

        await p.clear()
        await p.js("(() => { const i = document.querySelector('input'); i && i.focus(); return !!i; })()")
        await hold_space(p)
        got = await p.sent("/voice/command")
        check("Space inside a text field types, does not record", got == [], got)

        await p.js("document.activeElement && document.activeElement.blur()")
        found = False
        for _ in range(40):  # Tab until the keyboard lands on an ordinary button (Space belongs to it, not to the microphone)
            await p.key("keyDown", code="Tab", key="Tab", vk=9)
            await p.key("keyUp", code="Tab", key="Tab", vk=9)
            if await p.js("(() => { const a = document.activeElement; return !!a && a.tagName === 'BUTTON' && !a.hasAttribute('data-hold-to-talk') && a.matches(':focus-visible'); })()"):
                found = True
                break
        await p.clear()
        if found:
            await hold_space(p)
            got = await p.sent("/voice/command")
            check("Space on a keyboard-focused ordinary button activates it, does not record", got == [], got)
        else:
            check("Space on a keyboard-focused ordinary button (none reachable by Tab)", False, "no such button")

        await p.js("document.activeElement && document.activeElement.blur()")
        await p.clear()
        await hold_space(p, modifiers=1)
        got = await p.sent("/voice/command")
        check("⌥ Space still works (it is only advertised where the OS lets it through)", got == STARTED, got)

        # ── Voix page, Appel (conversation over WS /ai/voice) ──
        print("Voix · Appel (page /voice)")
        await p.goto(f"{base}/voice")
        await wait_ready(p)
        TALK = "button[data-hold-to-talk='call']"
        await p.clear()
        await hold_space(p)
        got = await p.sent("/ai/voice")
        check("Space hold → audio_start, frames, audio_end", got[-3:] == STARTED and got.count("audio_start") == 1, got)

        await p.clear()
        await hold_click(p, TALK)
        got = await p.sent("/ai/voice")
        check("click-and-hold on the big button → audio_start, frames, audio_end", got[-3:] == STARTED and got.count("audio_start") == 1, got)

        await p.clear()
        await hold_click(p, TALK, release_at=(20, 20))
        got = await p.sent("/ai/voice")
        check("release outside the big button still stops", got[-3:] == STARTED, got)

        await p.call("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=1)
        await p.clear()
        x, y = await p.center(TALK)
        await p.call("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": x, "y": y}])
        await asyncio.sleep(0.6)
        await p.call("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])
        await asyncio.sleep(0.6)
        got = await p.sent("/ai/voice")
        check("touch: press-and-hold the big button → audio_start, frames, audio_end", got[-3:] == STARTED and got.count("audio_start") == 1, got)
        await p.call("Emulation.setTouchEmulationEnabled", enabled=False)

        await p.clear()
        await hold_click(p, TALK, ms=60)
        got = await p.sent("/ai/voice")
        check("a simple click does not send a stub utterance (no audio_end; the server is told to drop it)", "audio_end" not in got and got[-1:] == ["audio_cancel"], got)

        await x_focus_click(p, TALK)
        await p.clear()
        await hold_space(p)
        got = await p.sent("/ai/voice")
        check("Space while the big button has focus: exactly ONE utterance", got.count("audio_start") == 1 and got[-1:] == ["audio_end"], got)

        await p.clear()
        await p.js("document.querySelector('input').focus()")
        await hold_space(p)
        got = await p.sent("/ai/voice")
        check("Space inside the 'type the caller's sentence' field does not record", got == [], got)

        # ── Voix page, Commande ──
        print("Voix · Commande (page /voice?mode=command)")
        await p.goto(f"{base}/voice?mode=command")
        await asyncio.sleep(1)
        HOLD = "button[data-hold-to-talk='command-page']"
        await p.clear()
        await hold_space(p)
        got = await p.sent("/voice/command")
        check("Space hold → ONE command recording (page + global shortcut do not both fire)", got == STARTED, got)

        await p.clear()
        await hold_click(p, HOLD)
        got = await p.sent("/voice/command")
        check("click-and-hold on the big button → ONE command recording", got == STARTED, got)
    finally:
        proc.terminate()
        shutil.rmtree(prof, ignore_errors=True)

    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)}/{len(results)} passed")
    return 1 if bad else 0


async def x_focus_click(p: Page, selector):
    x, y = await p.center(selector)
    await p.mouse("mouseMoved", x, y)
    await p.mouse("mousePressed", x, y)
    await p.mouse("mouseReleased", x, y)
    await asyncio.sleep(0.8)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="http://localhost:5173")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--shot", help="save a screenshot of the top bar to this png")
    a = ap.parse_args()
    sys.exit(asyncio.run(run(a.base, a.show, a.shot)))
