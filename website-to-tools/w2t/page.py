"""What the agent sees on a page, and how it acts on it like a person (eased mouse moves, human typing)."""
from __future__ import annotations

import random
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page

MAX_ELEMENTS = 80
MAX_TEXT = 3000

# Tags every visible interactive element with data-w2t=<n> and returns a short description of each.
_SNAPSHOT_JS = """
(maxEls) => {
  const sel = 'a[href], button, input, textarea, select, summary, [role=button], [role=tab], [role=link]';
  const out = [];
  document.querySelectorAll('[data-w2t]').forEach(e => e.removeAttribute('data-w2t'));
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    if (r.width < 2 || r.height < 2 || st.visibility === 'hidden' || st.display === 'none') continue;
    if (el.type === 'hidden' || el.closest('[aria-hidden=true]')) continue;
    const label = (el.getAttribute('aria-label') || el.innerText || el.value || el.placeholder ||
                   el.getAttribute('name') || el.getAttribute('href') || '').trim().replace(/\\s+/g, ' ');
    const n = out.length;
    el.setAttribute('data-w2t', String(n));
    out.push({n, tag: el.tagName.toLowerCase(), type: el.type || '', label: label.slice(0, 80),
              href: el.getAttribute('href') || '', inView: r.top >= 0 && r.bottom <= innerHeight});
    if (out.length >= maxEls) break;
  }
  return out;
}
"""


def snapshot(page: Page, attempts: int = 4) -> dict[str, Any]:
    """Read the page once it has settled. A navigation mid-read destroys the context, so wait and read again."""
    last: Exception | None = None
    for _ in range(attempts):
        try:
            page.wait_for_load_state("domcontentloaded")
            elements = page.evaluate(_SNAPSHOT_JS, MAX_ELEMENTS)
            text = page.evaluate("() => document.body ? document.body.innerText : ''") or ""
            return {"url": page.url, "title": page.title(), "elements": elements, "text": text[:MAX_TEXT]}
        except PlaywrightError as exc:
            last = exc
            page.wait_for_timeout(700)
    raise RuntimeError(f"page never settled long enough to read: {last}")


def glide_click(page: Page, n: int) -> None:
    """Scroll the element into view, move the mouse to it on an eased path, then click."""
    loc = page.locator(f'[data-w2t="{n}"]').first
    loc.scroll_into_view_if_needed()
    box = loc.bounding_box()
    if box is None:
        loc.click()
        return
    x = box["x"] + box["width"] * random.uniform(0.35, 0.65)
    y = box["y"] + box["height"] * random.uniform(0.35, 0.65)
    page.mouse.move(x, y, steps=random.randint(18, 30))
    page.wait_for_timeout(random.randint(120, 260))
    page.mouse.click(x, y)


def human_type(page: Page, n: int, text: str) -> None:
    glide_click(page, n)
    page.locator(f'[data-w2t="{n}"]').first.fill("")
    for ch in text:
        page.keyboard.type(ch)
        page.wait_for_timeout(random.randint(35, 110))


def scroll(page: Page, direction: str) -> None:
    delta = 650 if direction != "up" else -650
    for _ in range(6):
        page.mouse.wheel(0, delta / 6)
        page.wait_for_timeout(60)
