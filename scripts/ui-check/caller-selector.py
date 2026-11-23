#!/usr/bin/env python3
"""
Browser check of the caller-identity selector (header badge on the Voix page): who is on the line is DECLARED in the UI and
sent on the WS `start` message (role / clientId / actorName), persisted in localStorage, and re-sent when it changes.

    uv run --with websockets scripts/ui-check/caller-selector.py          # needs the stack up (make up) on :5173
    uv run --with websockets scripts/ui-check/caller-selector.py --shot /var/tmp/caller.png

Same harness as hold-to-talk.py (own throw-away Edge, real input events). The page's WebSocket to /ai/voice is replaced by a recorder
that answers `ready` like the server does (it echoes the declared role): no AI quota is spent, the ERP is only read (client list).
"""

import argparse
import asyncio
import base64
import importlib.util
import json
import sys
from pathlib import Path

import websockets

spec = importlib.util.spec_from_file_location("htt", Path(__file__).with_name("hold-to-talk.py"))
htt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(htt)

STUB = r"""
(() => {
  window.__starts = [];
  const Real = window.WebSocket;
  class Fake {
    constructor(url) { this.url = url; this.readyState = 0; this.onopen = this.onmessage = this.onclose = this.onerror = null; setTimeout(() => { this.readyState = 1; this.onopen && this.onopen({}); }, 0); }
    send(d) {
      if (typeof d !== "string") return;
      const m = JSON.parse(d);
      if (m.type !== "start") return;
      window.__starts.push(m);
      const role = m.role === "client" && !m.clientId ? "unknown" : (m.role || "unknown");
      setTimeout(() => this.onmessage && this.onmessage({ data: JSON.stringify({ type: "ready", sessionId: "fake", stt: "fake", tts: "fake", llm: "fake", role, clientId: m.clientId, actorName: m.actorName }) }), 0);
    }
    close() { this.readyState = 3; this.onclose && this.onclose({}); }
    addEventListener() {} removeEventListener() {}
  }
  const W = function (url, p) { return /\/ai\/voice/.test(String(url)) ? new Fake(String(url)) : new Real(url, p); };
  Object.assign(W, { CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3 });
  W.prototype = Real.prototype;
  window.WebSocket = W;
})();
"""

BADGE = 'button[aria-haspopup="dialog"]'
DIALOG = '[role="dialog"][aria-label="Identité de l\'appelant"]'


async def click_text(p, root: str, selector: str, text: str) -> bool:
    return await p.js(
        f"(() => {{ const e = [...document.querySelectorAll({json.dumps(root + ' ' + selector)})].find(x => x.textContent.trim().startsWith({json.dumps(text)})); if (!e) return false; e.click(); return true; }})()"
    )


async def starts(p):
    return await p.js("window.__starts") or []


async def wait_starts(p, n: int):
    for _ in range(40):
        if len(await starts(p)) >= n:
            return
        await asyncio.sleep(0.2)


async def run(base: str, show: bool, shot: str | None) -> int:
    proc, prof = htt.start_edge(show)
    check = htt.check
    try:
        p = htt.Page(await websockets.connect(await htt.wait_page(), max_size=None))
        await p.call("Page.enable")
        await p.call("Runtime.enable")
        await p.call("Page.addScriptToEvaluateOnNewDocument", source=STUB)
        await p.goto(f"{base}/voice")
        await p.js("localStorage.removeItem('kit.caller')")
        await p.goto(f"{base}/voice")
        await wait_starts(p, 1)

        s = await starts(p)
        check("default identity = unknown (the safest), declared on start", s and s[0].get("role") == "unknown" and "clientId" not in s[0], json.dumps(s))
        check("no hard-coded 'Agent vocal' author any more", s and "actorName" not in s[0], json.dumps(s))
        check("badge says « Non identifié »", "Non identifié" in (await p.js(f"document.querySelector('{BADGE}')?.textContent") or ""))

        await p.js(f"document.querySelector('{BADGE}').click()")
        await asyncio.sleep(0.4)
        dialog = await p.js(f"document.querySelector({json.dumps(DIALOG)})?.textContent")
        check("popover opens and says « Identité déclarée (démo) »", dialog and "Identité déclarée (démo)" in dialog and "En production" in dialog, str(dialog)[:80])

        n = len(await starts(p))
        check("« Client » without a client id changes nothing on the wire (nobody)", await click_text(p, DIALOG, '[role="radio"]', "Client") and len(await starts(p)) == n)
        await asyncio.sleep(0.3)
        check("client Select appears (required)", "Client (obligatoire)" in (await p.js(f"document.querySelector({json.dumps(DIALOG)}).textContent") or ""))
        await p.js(f"[...document.querySelectorAll({json.dumps(DIALOG + ' button')})].find(b => b.textContent.includes('Choisir le client')).click()")
        await asyncio.sleep(0.6)
        picked = await click_text(p, "", '[role="listbox"] [role="option"]', "Le Refuge Payet")
        await wait_starts(p, n + 1)
        s = await starts(p)
        last = s[-1]
        check(
            "picking Le Refuge Payet sends start {role: client, clientId, actorName}",
            picked and last.get("role") == "client" and last.get("clientId") == "cli_0082" and last.get("actorName") == "Le Refuge Payet",
            json.dumps(last),
        )
        check("the badge shows the identity (still open: the Select list did not close the popover)", await p.js(f"!!document.querySelector({json.dumps(DIALOG)})"))
        stored = await p.js("localStorage.getItem('kit.caller')")
        check("last choice persisted in localStorage", stored and "cli_0082" in stored, str(stored))

        n = len(await starts(p))
        await click_text(p, DIALOG, '[role="radio"]', "Commercial")
        await asyncio.sleep(0.4)
        await p.js(f"(() => {{ const i = document.querySelector({json.dumps(DIALOG + ' input')}); i.focus(); }})()")
        await p.call("Input.insertText", text="Thibault")
        check("typing a name sends nothing yet (committed on blur)", len(await starts(p)) == n + 1)  # the role change itself = 1 start
        await p.js(f"document.querySelector({json.dumps(DIALOG + ' input')}).blur()")
        await wait_starts(p, n + 2)
        last = (await starts(p))[-1]
        check("blur commits: start {role: sales, actorName: Thibault}", last.get("role") == "sales" and last.get("actorName") == "Thibault", json.dumps(last))

        if shot:
            data = await p.call("Page.captureScreenshot", format="png")
            Path(shot).write_bytes(base64.b64decode(data["data"]))
            print(f"  screenshot: {shot}")

        await p.js("document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))")
        await asyncio.sleep(0.3)
        check("Escape closes the popover", not await p.js(f"!!document.querySelector({json.dumps(DIALOG)})"))
        await p.goto(f"{base}/voice")
        await wait_starts(p, 1)
        s = await starts(p)
        check("after a reload the first start already carries the stored identity", s and s[0].get("role") == "sales" and s[0].get("actorName") == "Thibault", json.dumps(s[:1]))
        await p.js("localStorage.removeItem('kit.caller')")
    finally:
        proc.terminate()
    failed = [r for r in htt.results if not r[1]]
    print(f"\n{len(htt.results) - len(failed)}/{len(htt.results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:5173")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--shot")
    a = ap.parse_args()
    sys.exit(asyncio.run(run(a.base, a.show, a.shot)))
