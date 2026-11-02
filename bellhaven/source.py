"""Fetch public website evidence and read the complete CRM account inventory."""
import hashlib
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DEFAULT_BASE = "https://analyst-assessment-production.up.railway.app"


def get(url, token=None, params=None):
    # This module deliberately exposes no mutation method. Tokens are never sent
    # to the public website, nor forwarded to redirect destinations.
    with requests.Session() as session:
        session.mount("https://", HTTPAdapter(max_retries=Retry(
            total=2, backoff_factor=0.5, status_forcelist=[429, 502, 503, 504],
            allowed_methods=["GET"], respect_retry_after_header=False,
        )))
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        response = session.get(url, params=params, headers=headers,
                               timeout=(10, 30), allow_redirects=False)
        response.raise_for_status()
        if response.is_redirect:
            raise ValueError("Unexpected redirect; refusing to forward credentials")
        return response


def parse_location(document, url):
    soup = BeautifulSoup(document, "html.parser")
    heading = soup.select_one(".wrap h1")
    fields = {dt.get_text(" ", strip=True): dt.find_next_sibling("dd")
              for dt in soup.select("dl.detail dt")}
    if not heading or not fields.get("Address") or not fields.get("Care Offerings"):
        raise ValueError(f"Incomplete location page: {url}")
    address = fields["Address"].get_text("\n", strip=True).splitlines()
    if len(address) != 2:
        raise ValueError(f"Unexpected address structure: {url}")
    match = re.fullmatch(r"(.+),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)", address[1])
    if not match:
        raise ValueError(f"Unparseable city/state/ZIP: {url}")
    care = [node.get_text(" ", strip=True)
            for node in fields["Care Offerings"].select(".badge")]
    if not care or not address[0].strip():
        raise ValueError(f"Missing required location fields: {url}")
    return dict(name=heading.get_text(" ", strip=True), street=address[0].strip(),
                city=match[1], state=match[2], zip=match[3], care_offerings=care,
                phone=fields["Phone"].get_text(" ", strip=True) if fields.get("Phone") else "",
                administrator=fields["Administrator"].get_text(" ", strip=True) if fields.get("Administrator") else "",
                source_url=url,
                source_sha256=hashlib.sha256(document.encode()).hexdigest())


def scrape(base=DEFAULT_BASE):
    """Follow directory pagination plus location links on home/about pages."""
    queue = [base + "/", base + "/about", base + "/communities"]
    visited, details, pages = set(), set(), {}
    directory_count = None
    while queue:
        url = queue.pop(0)
        if url in visited:
            continue
        if len(visited) >= 100:
            raise ValueError("Unexpected website pagination size")
        visited.add(url)
        document = get(url).text
        pages[url] = document
        soup = BeautifulSoup(document, "html.parser")
        if urlsplit(url).path == "/communities":
            count = re.search(r"(\d+) communities listed", soup.get_text(" ", strip=True))
            if count:
                if directory_count is not None and directory_count != int(count[1]):
                    raise ValueError("Directory count changed during scrape; retry")
                directory_count = int(count[1])
        for link in soup.select("a[href]"):
            target = urljoin(url, link["href"]).split("#")[0]
            parts = urlsplit(target)
            if (parts.scheme, parts.netloc) != (urlsplit(base).scheme, urlsplit(base).netloc):
                continue
            if re.fullmatch(r"/communities/[^/]+", parts.path):
                details.add(target)
            elif parts.path == "/communities" and target not in visited:
                queue.append(target)
    if not details or directory_count is None:
        raise ValueError("No valid directory found; refusing reconciliation")
    # Check directory links independently: a missing directory page must not
    # produce false 'no longer listed' findings.
    directory_links = set()
    for url, document in pages.items():
        if urlsplit(url).path == "/communities":
            soup = BeautifulSoup(document, "html.parser")
            for link in soup.select(".card h3 a[href]"):
                directory_links.add(urljoin(url, link["href"]))
    if len(directory_links) != directory_count:
        raise ValueError(f"Incomplete directory: expected {directory_count}, got {len(directory_links)}")

    def fetch_detail(url):
        document = get(url).text
        return url, document, parse_location(document, url)

    locations = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        for url, document, location in executor.map(fetch_detail, sorted(details)):
            pages[url] = document
            locations.append(location)
    return locations, pages, {"directory_locations": directory_count,
                              "all_locations": len(locations),
                              "extra_location_urls": sorted(details - directory_links)}


def fetch_accounts(token, base=DEFAULT_BASE):
    accounts, seen = [], set()
    page, expected_total = 1, None
    while True:
        body = get(base + "/api/v1/accounts", token,
                   {"page": page, "page_size": 50}).json()
        if not isinstance(body, dict) or not isinstance(body.get("data"), list):
            raise ValueError("Unexpected account response")
        total = body["total"]
        if expected_total is None:
            expected_total = total
        if total != expected_total or body.get("page") != page:
            raise ValueError("CRM inventory changed or pagination was ignored; retry")
        for account in body["data"]:
            account_id = account["account_id"]
            if account_id in seen:
                raise ValueError("Repeated account across pages; refusing partial inventory")
            seen.add(account_id)
            accounts.append(account)
        if len(accounts) == total:
            return accounts
        if not body["data"] or len(accounts) > total:
            raise ValueError("Incomplete CRM account inventory")
        page += 1
