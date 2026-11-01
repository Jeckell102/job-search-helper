"""Read-only Y Combinator company jobs pages.

YC exposes a company-scoped jobs page, but not a public ATS API.  An explicit
empty state is still machine-verifiable; non-empty inventories fail closed
until YC exposes stable public detail records suitable for full integration.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urljoin

from .ats import FetchError, Inventory, text
from .discovery import CareersTransport


SOURCE = "https://www.ycombinator.com/companies/surtr-defense-systems/jobs"
POLYMATH = "https://www.ycombinator.com/companies/polymath-robotics/jobs"

class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.links=[]; self.parts=[]; self.title=[]; self.in_title=False
    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        if tag == "a" and a.get("href"): self.links.append(a["href"])
        if tag == "title": self.in_title=True
    def handle_data(self, data):
        self.parts.append(data)
        if self.in_title: self.title.append(data)
    def handle_endtag(self, tag):
        if tag == "title": self.in_title=False


def fetch_ycombinator(url, company_id, company, transport=None):
    if url not in {SOURCE, POLYMATH}:
        return Inventory("unsupported", reason="Y Combinator adapter requires the verified company jobs page.",
                         source_url=url, ats="Y Combinator")
    client = transport or CareersTransport()
    try:
        response = client.get(url)
        if response.status in (401, 403, 429):
            raise FetchError("blocked", "Y Combinator public jobs page is unavailable.")
        if response.status != 200:
            raise FetchError("partial", "Y Combinator public jobs page was unavailable.")
        body = response.body.decode("utf-8", "replace")
        if url == POLYMATH:
            index=_Page(); index.feed(body)
            detail_urls=[]
            for href in index.links:
                absolute=urljoin(url, href)
                if absolute.startswith(POLYMATH + "/") and absolute not in detail_urls: detail_urls.append(absolute)
            if len(detail_urls) != 5: raise FetchError("partial", f"Polymath Robotics jobs changed; found {len(detail_urls)} detail links.")
            jobs=[]
            for detail_url in detail_urls:
                dresp=client.get(detail_url)
                if dresp.status != 200: raise FetchError("partial", "Polymath Robotics job detail was unavailable.")
                page=_Page(); page.feed(dresp.body.decode("utf-8", "replace")); title=text(page.title[0] if page.title else "").split(" at Polymath Robotics",1)[0]
                description=text(" ".join(page.parts))
                if not title or len(description) < 500: raise FetchError("partial", "Polymath Robotics job detail lacks a full description.")
                jobs.append({"posting_id": detail_url.rsplit("/",1)[-1], "ats":"Y Combinator", "company_id":company_id, "company":company, "title":title, "description":description, "url":detail_url})
            reread=_Page(); reread.feed(client.get(url).body.decode("utf-8", "replace")); reread_urls=[]
            for href in reread.links:
                absolute=urljoin(url, href)
                if absolute.startswith(POLYMATH + "/") and absolute not in reread_urls: reread_urls.append(absolute)
            if reread_urls != detail_urls: raise FetchError("partial", "Polymath Robotics job inventory changed during reread.")
            return Inventory("complete", jobs, "Y Combinator: retrieved five complete Polymath Robotics job details.", url, "Y Combinator")
        visible = re.sub(r"<[^>]+>", " ", body)
        visible = " ".join(visible.split())
        if re.search(r"Jobs at\s+.{1,200}?\s+No jobs at\s+.{1,200}?\s+are currently posted", visible, re.I):
            return Inventory("complete", [], "Y Combinator: verified explicit empty company jobs inventory.", url, "Y Combinator")
        raise FetchError("unsupported", "Y Combinator exposes no stable public job-detail inventory for this company.")
    except FetchError as error:
        return Inventory(error.status, [], error.reason, url, "Y Combinator")
    except (AttributeError, UnicodeError):
        return Inventory("partial", [], "Y Combinator public page schema validation failed.", url, "Y Combinator")
