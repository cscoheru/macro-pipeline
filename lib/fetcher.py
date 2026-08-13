"""Source fetchers.
Phase 1: FRED CSV.
Phase 3: China HTML — listing discovery + release fetch + tag strip (财政部/统计局).
"""
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

FRED_CSV_BASE = "https://fred.stlouisfed.org/graph/fredgraph.csv?id="
TIMEOUT = 30
_BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def fetch_text(url: str, timeout: int = TIMEOUT) -> str:
    """GET url, return text. Raises on HTTP error."""
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.text


def fetch_fred_series(series_id: str, timeout: int = TIMEOUT) -> str:
    """Fetch raw FRED CSV for one series (no API key required for CSV endpoint)."""
    return fetch_text(FRED_CSV_BASE + series_id, timeout=timeout)


def parse_fred_csv(csv_text: str):
    """Parse FRED CSV -> list of (date_str, float_value), oldest -> newest.

    Skips missing values encoded as '.' and unparseable rows.
    """
    rows = []
    lines = csv_text.strip().splitlines()
    if len(lines) < 2:
        return rows
    for line in lines[1:]:  # first line is the header
        parts = line.split(",")
        if len(parts) < 2:
            continue
        date = parts[0].strip().strip('"')
        val = parts[1].strip().strip('"')
        if val in (".", ""):
            continue
        try:
            rows.append((date, float(val)))
        except ValueError:
            continue
    return rows


# ---------------------------------------------------------------------------
# China HTML helpers (Phase 3)
# ---------------------------------------------------------------------------

def fetch_html(url: str, timeout: int = TIMEOUT) -> str:
    """GET an HTML page with a browser UA, forcing UTF-8 (CN gov pages are utf-8
    but requests often mis-guesses ISO-8859-1). Returns decoded text."""
    r = requests.get(url, headers=_BROWSER_HEADERS, timeout=timeout)
    r.raise_for_status()
    if not r.encoding or r.encoding.lower() in ("iso-8859-1",):
        r.encoding = "utf-8"
    return r.text


def strip_tags(html: str) -> str:
    """Strip HTML to clean text (script/style removed first). Keeps text-node order.

    CN gov releases wrap digits across multiple <span>s (e.g. '4' '.' '7' '%'),
    so get_text(' ') yields '4 .7%'. We re-join whitespace that sits between
    numeric characters to restore '4.7%'.
    """
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    text = re.sub(r"(?<=[\d.,])\s+(?=[\d.,])", "", text)
    return text


def discover_latest_release(listing_url: str, title_regex: str):
    """Fetch a listing page, return (title, release_url) of the newest <a> whose
    title matches `title_regex`, or (None, None). Resolves relative URLs.
    These CN gov listings are newest-first, so first match = latest."""
    html = fetch_html(listing_url)
    soup = BeautifulSoup(html, "lxml")
    seen = []
    for a in soup.find_all("a", href=True):
        title = a.get_text(strip=True)
        if title and re.search(title_regex, title):
            url = urljoin(listing_url, a["href"])
            if url not in [u for _, u in seen]:
                seen.append((title, url))
    if not seen:
        return None, None
    return seen[0]


# ---------------------------------------------------------------------------
# JS-challenge WAF fetcher (Phase 3 — e.g. customs.gov.cn uses 加速乐/JSL)
# ---------------------------------------------------------------------------

def fetch_html_waf(url: str, timeout: int = 30000) -> str:
    """Fetch a page behind a JS-challenge WAF (e.g. 加速乐/JSL) via headless Chromium.
    The browser executes the challenge JS, gets the cookie, and returns rendered HTML.
    Heavier than fetch_html — only use for sources marked waf:true."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(url, timeout=timeout, wait_until="load")
            # JSL flow: page loads -> challenge JS solves -> reload/redirect -> real content.
            # Wait that cycle out: a few networkidle + settle passes.
            for _ in range(3):
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                page.wait_for_timeout(2500)
            # content() can throw if caught mid-navigation; retry a few times.
            last = None
            for _ in range(4):
                try:
                    return page.content()
                except Exception as e:
                    last = e
                    page.wait_for_timeout(1000)
            raise last
        finally:
            browser.close()


def discover_latest_release_waf(listing_url: str, title_regex: str):
    """Same as discover_latest_release but renders via headless browser (for WAF sites)."""
    html = fetch_html_waf(listing_url)
    soup = BeautifulSoup(html, "lxml")
    seen = []
    for a in soup.find_all("a", href=True):
        title = a.get_text(strip=True)
        if title and re.search(title_regex, title):
            url = urljoin(listing_url, a["href"])
            if url not in [u for _, u in seen]:
                seen.append((title, url))
    if not seen:
        return None, None
    return seen[0]
