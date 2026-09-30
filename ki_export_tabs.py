#!/usr/bin/env python3
"""KI-Export: Gemini / Perplexity / ChatGPT Tabs aus dem laufenden Browser exportieren.

Voraussetzung:
  1) Chrome/Edge mit Fernsteuerungsport starten:
     Windows: chrome.exe --remote-debugging-port=9222
     macOS:   open -na "Google Chrome" --args --remote-debugging-port=9222
     Linux:   google-chrome --remote-debugging-port=9222
  2) In diesem Browser: Tabs mit Gemini (beide Accounts), Perplexity, ChatGPT oeffnen.
  3) pip install playwright   (Browser-Download nicht noetig, wir verbinden uns nur)

Ausfuehrung:
  python ki_export_tabs.py [--cdp http://127.0.0.1:9222] [--out ~/KI-WISSEN] [--auto]

Ohne --auto fragt das Skript interaktiv pro Tab, ob er zu TTT oder GG gehoert
[UNKLAR-Kennzeichnung: DOM-basierte Account-Erkennung ist unzuverlaessig).

Pro Tab werden erzeugt:
  <out>/<Anbieter>/<TTT|GG>/<datum>/<slug>.md          Volltext der Konversation
  <out>/<Anbieter>/<TTT|GG>/<datum>/<slug>.mhtml       vollstaendiger Seiten-Snapshot
  <out>/<Anbieter>/<TTT|GG>/<datum>/<slug>.png         Screenshot
  <out>/<Anbieter>/<TTT|GG>/<datum>/<slug>.json        URL, Titel, Zeitstempel
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit("playwright fehlt. Installieren mit: pip install playwright")

PROVIDERS = [
    ("gemini", re.compile(r"gemini\.google\.com", re.I)),
    ("perplexity", re.compile(r"perplexity\.ai|pplx\.ai", re.I)),
    ("chatgpt", re.compile(r"chatgpt\.com|chat\.openai\.com", re.I)),
]
ACCOUNTS = ("TTT", "GG")

EXTRACT_JS = """
() => {
  const pick = (sels) => {
    for (const sel of sels) {
      const el = document.querySelector(sel);
      if (el && el.innerText.trim().length > 40) return el.innerText.trim();
    }
    return null;
  };
  let text = null;
  if (location.hostname.includes('gemini.google.com')) {
    text = pick(['main', 'conversation', 'body']);
  } else if (location.hostname.includes('perplexity')) {
    text = pick(['main', 'article', 'div.prose', 'body']);
  } else {
    text = pick(['main', 'div[role="presentation"]', 'body']);
  }
  return text || document.body.innerText.trim();
}
"""


def slugify(s: str, fallback: str) -> str:
    s = re.sub(r"[^\w\s-]", "", s, flags=re.U).strip().lower()
    s = re.sub(r"[\s_-]+", "-", s)[:60]
    return s or fallback


def detect_provider(url: str):
    for name, rx in PROVIDERS:
        if rx.search(urlparse(url).netloc):
            return name
    return None


def ask_account(title: str, url: str) -> str:
    print(f"\nTab: {title}\n     {url}")
    while True:
        a = input("  Account? [1]=TTT [2]=GG [s]=skip: ").strip().lower()
        if a in ("1", "ttt"):
            return "TTT"
        if a in ("2", "gg"):
            return "GG"
        if a in ("s", "skip"):
            return "SKIP"


def main() -> None:
    ap = argparse.ArgumentParser(description="KI-Tabs aus laufendem Browser exportieren")
    ap.add_argument("--cdp", default="http://127.0.0.1:9222", help="CDP-Endpoint des Browsers")
    ap.add_argument("--out", default=str(Path.home() / "KI-WISSEN"), help="Zielordner")
    ap.add_argument("--auto", action="store_true",
                    help="keine Account-Rueckfrage; Dateien landen unter '_UNKLAR'")
    args = ap.parse_args()

    out_root = Path(args.out).expanduser()
    date_dir = _dt.date.today().isoformat()
    stats = {"exported": 0, "skipped": 0}

    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(args.cdp)
        except Exception as e:
            sys.exit(f"Keine Verbindung zu {args.cdp}: {e}\n"
                     "Browser starten mit: chrome --remote-debugging-port=9222")

        pages = []
        for ctx in browser.contexts:
            pages.extend(ctx.pages)

        targets = [(pg, detect_provider(pg.url)) for pg in pages]
        targets = [(pg, prov) for pg, prov in targets if prov and not pg.url.startswith("chrome://")]

        if not targets:
            sys.exit("Keine Gemini-/Perplexity-/ChatGPT-Tabs im verbundenen Browser gefunden.")

        print(f"{len(targets)} KI-Tab(s) gefunden.")
        for page, provider in targets:
            title = (page.title() or "").strip() or "ohne-titel"
            url = page.url
            if args.auto:
                account = "_UNKLAR"
            else:
                account = ask_account(title, url)
                if account == "SKIP":
                    stats["skipped"] += 1
                    continue

            dest = out_root / provider / account / date_dir
            dest.mkdir(parents=True, exist_ok=True)
            base = f"{_dt.datetime.now().strftime('%H%M%S')}-{slugify(title, provider)}"

            try:
                body = page.evaluate(EXTRACT_JS)
            except Exception as e:
                body = f"[UNKLAR] Textextraktion fehlgeschlagen: {e}"
            (dest / f"{base}.md").write_text(
                f"# {title}\n\n- URL: {url}\n"
                f"- Export: {_dt.datetime.now().isoformat(timespec='seconds')}\n"
                f"- Account: {account}\n\n---\n\n{body}\n",
                encoding="utf-8",
            )

            try:
                page.screenshot(path=str(dest / f"{base}.png"), full_page=False)
            except Exception:
                pass
            try:
                mhtml = None
                cdp = context_cdp = page.context.new_cdp_session(page)
                result = cdp.send("Page.captureSnapshot", {"format": "mhtml"})
                mhtml = result.get("data")
                cdp.detach()
                if mhtml:
                    (dest / f"{base}.mhtml").write_text(mhtml, encoding="utf-8")
            except Exception:
                pass

            (dest / f"{base}.json").write_text(
                json.dumps({"url": url, "title": title, "provider": provider,
                            "account": account,
                            "exported_at": _dt.datetime.now().isoformat(timespec="seconds")},
                           ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            stats["exported"] += 1
            print(f"  -> {dest / base}.md")

    print(f"\nFertig: {stats['exported']} exportiert, {stats['skipped']} uebersprungen.")
    print(f"Zielordner: {out_root}")


if __name__ == "__main__":
    main()
