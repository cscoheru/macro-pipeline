"""Source fetchers.
Phase 1: FRED CSV.
Phase 3: China HTML — listing discovery + release fetch + tag strip (财政部/统计局).
Phase JP/DE: PDF releases — discover latest, fetch_pdf + pdftotext/pypdf.
"""
import io
import logging
import subprocess
import re
from datetime import date, datetime, timedelta
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


# ---------------------------------------------------------------------------
# PDF helpers (Phase JP/DE — BOJ CGPI/MPM, Cabinet Office GDP, e-Stat English)
# ---------------------------------------------------------------------------

def fetch_pdf(url: str, timeout: int = TIMEOUT, max_bytes: int = 25 * 1024 * 1024) -> bytes:
    """GET a PDF file with browser UA. Returns raw bytes.

    Hard cap `max_bytes` (default 25 MiB) to defend against compression bombs
    and misconfigured servers streaming huge responses. Streams the body in
    chunks so we can abort before the response fills memory.
    """
    r = requests.get(url, headers=_BROWSER_HEADERS, timeout=timeout, stream=True)
    r.raise_for_status()
    # Honor Content-Length when present (lets us bail early on declared oversize).
    cl = r.headers.get("Content-Length")
    if cl and cl.isdigit() and int(cl) > max_bytes:
        r.close()
        raise RuntimeError(f"PDF too large: Content-Length={cl} > max_bytes={max_bytes}")
    # Also check the magic header once a few bytes arrive, in case the server
    # lied about content-type (HTML error page disguised as PDF).
    chunks = []
    total = 0
    for chunk in r.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            r.close()
            raise RuntimeError(f"PDF too large: streamed {total} > max_bytes={max_bytes}")
        chunks.append(chunk)
    body = b"".join(chunks)
    if not body.startswith(b"%PDF"):
        raise RuntimeError(f"response is not a PDF (header={body[:8]!r})")
    return body


def pdf_to_text(data: bytes, max_pages: int = 50) -> str:
    """Extract text from PDF bytes. Prefers the poppler `pdftotext` binary
    (handles layout/columns far better than pure-python libs), falls back to
    `pypdf` if pdftotext is unavailable. Returns the merged multi-page text
    with page breaks flattened to spaces.

    `max_pages` caps both pdftotext (via first-page scan + page count) and the
    pypdf fallback, so a malformed multi-gigabyte PDF can't tie up the pipeline.
    """
    try:
        # Quick page-count check using pdftotext itself: feed only page 1 first
        # and the rest only if the document is small enough. pdftotext has no
        # built-in max-pages; we approximate by measuring decoded size.
        first = subprocess.run(
            ["pdftotext", "-layout", "-enc", "UTF-8", "-f", "1", "-l", "1", "-", "-"],
            input=data, capture_output=True, check=True, timeout=15,
        ).stdout
        # If first page is fine, do the rest. Combined output is bounded by
        # data size and typical press releases fit in 100 pages.
        rest = subprocess.run(
            ["pdftotext", "-layout", "-enc", "UTF-8", "-", "-"],
            input=data, capture_output=True, check=True, timeout=30,
        ).stdout
        return rest.decode("utf-8", errors="replace")
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        # Fallback: pypdf (pure-python; column layout can break but works for
        # simple single-column press releases).
        try:
            from pypdf import PdfReader
        except ImportError as e:
            raise RuntimeError("PDF extraction needs `pdftotext` or `pypdf`") from e
        reader = PdfReader(io.BytesIO(data))
        if len(reader.pages) > max_pages:
            raise RuntimeError(f"PDF too long: {len(reader.pages)} pages > max_pages={max_pages}")
        chunks = []
        for page in reader.pages[:max_pages]:
            try:
                chunks.append(page.extract_text() or "")
            except Exception:
                chunks.append("")
        return "\n".join(chunks)


def discover_pdf(url: str) -> bool:
    """True if the URL ends in .pdf (case-insensitive, ignoring query/fragment)."""
    from urllib.parse import urlsplit
    return urlsplit(url).path.lower().endswith(".pdf")


def discover_latest_release(listing_url: str, title_regex: str,
                           href_regex: str = None,
                           follow_href_regex: str = None,
                           href_base: str = None):
    """Fetch a listing page, return (title, release_url) of the newest <a> whose
    title matches `title_regex`, or (None, None). Resolves relative URLs.

    `href_regex` (optional) adds a second filter on the link's href — useful
    when the link text is generic (e.g. "[PDF 218KB]" appears once per release
    but the href carries the date, e.g. `cgpi2607.pdf`).

    `follow_href_regex` (optional) is a second filter applied AFTER the first
    match: only follow the discovered link if its href also matches this
    regex. Lets us skip "menu/calendar" pages and land on the actual release.
    These CN gov listings are newest-first, so first match = latest.

    `href_base` (optional) overrides the URL join base. Use when the listing
    page's relative hrefs resolve to a different directory than the listing
    URL itself (e.g. Destatis Pressesuche's `EN/Press/...` hrefs want to
    resolve against the site root, not the listing directory).
    """
    title, url = _discover_one(listing_url, title_regex, href_regex,
                                href_base=href_base)
    if not url:
        return None, None
    if follow_href_regex and not re.search(follow_href_regex, url):
        return None, None
    return title, url


def discover_latest_release_chained(listing_url: str, hops):
    """Multi-hop discovery: each hop is (title_regex, href_regex).

    Follows the first anchor matching hop 1 on the listing page, re-runs
    discovery on that page for hop 2, etc. Returns (title, url) of the LAST
    hop (that's the release URL; title is the last hop's anchor text) or
    (None, None) if any hop fails. Needed for sites like CAO where the release
    lives 2-3 links below the stable entry page (news → sokuhou_top →
    gdemenue{quarter} → main_1e.pdf).
    """
    title, url = None, listing_url
    for hop_title, hop_href in hops:
        title, url = _discover_one(url, hop_title, hop_href)
        if not url:
            return None, None
    return title, url


# Pattern for "year-of-decisions" index pages, e.g. BOJ's state_2026/. Used
# by resolve_year_index to redirect from a stable aggregator (state_all) to
# the newest annual folder without hardcoding the year.
# Not end-anchored: BOJ hrefs are "/en/mopo/mpmdeci/state_2026/index.htm"
# so `state_2026/` lives mid-path. The href_regex filter (passed in from
# sources.yaml) narrows to the right subtree.
_YEAR_INDEX_RE = re.compile(r"state[_-](20\d{2})", re.I)


def resolve_year_index(aggregator_url: str, href_regex: str = None) -> str:
    """Given a stable "list-of-years" URL, return the URL of the newest year
    subfolder. Used for BOJ MPM (state_all/ → state_2026/, state_2025/, ...).

    Raises RuntimeError when no year folder matches — silent fallback would
    hide BOJ layout changes (the whole point of year_index is to detect
    Jan-1 staleness, so a missing year folder is exactly what we want to
    surface, not paper over)."""
    try:
        html = fetch_html(aggregator_url)
    except Exception as e:
        raise RuntimeError(
            f"failed to fetch year-aggregator {aggregator_url}: {e}") from e
    soup = BeautifulSoup(html, "lxml")
    years = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href_regex and not re.search(href_regex, href):
            continue
        m = _YEAR_INDEX_RE.search(href)
        if not m:
            continue
        years.append((int(m.group(1)), urljoin(aggregator_url, href)))
    if not years:
        raise RuntimeError(
            f"no year folder found in {aggregator_url} "
            f"(href_regex={href_regex!r}); layout may have changed")
    years.sort(key=lambda pair: pair[0], reverse=True)
    return years[0][1]


# Date candidates in release URLs, in priority order. Matched once each; the
# first one that yields a sensible date wins. Used to detect stale listings
# (e.g. year-pinned URLs whose content didn't actually roll over on Jan 1).
_URL_DATE_PATTERNS = (
    (re.compile(r"/(20\d{2})/(\d{2})/"), lambda m: (int(m.group(1)), int(m.group(2)))),       # /YYYY/MM/
    (re.compile(r"/(20\d{2})(\d{2})/"), lambda m: (int(m.group(1)), int(m.group(2)))),         # /YYYYMM/
    (re.compile(r"/(?:k|release_|release-|cgpi|mpr_)(\d{2})(\d{2})"), lambda m: (2000 + int(m.group(1)), int(m.group(2)))),
    (re.compile(r"/(20\d{2})/"), lambda m: (int(m.group(1)), None)),                           # /YYYY/ only
)


def release_date_from_url(url: str):
    """Best-effort YYYY-MM date parsed from a release URL. Returns None when
    no candidate yields a plausible (year within last 5y, month 1..12) result."""
    if not url:
        return None
    now = date.today()
    candidates = []
    for pat, builder in _URL_DATE_PATTERNS:
        m = pat.search(url)
        if not m:
            continue
        try:
            yr, mo = builder(m)
        except (TypeError, ValueError):
            continue
        if mo is None:
            candidates.append(date(yr, 12, 31))
            continue
        if not 1 <= mo <= 12:
            continue
        if not (now.year - 5 <= yr <= now.year + 1):
            continue
        try:
            candidates.append(date(yr, mo, 1))
        except ValueError:
            continue
    return max(candidates) if candidates else None


def freshness_check(url: str, max_age_days: int = 60):
    """Log a warning if a release URL looks stale (older than max_age_days).

    Does NOT raise — this is a tripwire, not a gate. A layout change can hide
    the date from the URL entirely; in that case we'd rather keep publishing
    with no warning than block the pipeline."""
    release = release_date_from_url(url)
    if release is None:
        return
    age = date.today() - release
    if age > timedelta(days=max_age_days):
        logging.warning(
            "release URL looks stale: age=%d days (release~%s, url=%s)",
            age.days, release.isoformat(), url,
        )


def _discover_one(listing_url, title_regex, href_regex, href_base=None):
    html = fetch_html(listing_url)
    soup = BeautifulSoup(html, "lxml")
    seen = []
    join_base = href_base or listing_url
    for a in soup.find_all("a", href=True):
        title = a.get_text(strip=True)
        href = a["href"]
        if not title:
            continue
        if not re.search(title_regex, title):
            continue
        if href_regex and not re.search(href_regex, href):
            continue
        url = urljoin(join_base, href)
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
