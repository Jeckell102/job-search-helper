"""Peplink's employer-managed public careers cards and complete detail panels."""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from html.parser import HTMLParser
import re

from .ats import FetchError, HTTPResponse, Inventory, _base
from .discovery import CareersTransport

SOURCE = "https://www.peplink.com/company/career/"
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


@dataclass
class _Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)
    closed: bool = False


class _DOM(HTMLParser):
    def __init__(self, body):
        super().__init__(convert_charrefs=True)
        self.root = _Node("document")
        self.stack = [self.root]
        self.feed(body)
        self.close()

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, dict(attrs), closed=tag in VOID)
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                self.stack[index].closed = True
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def _walk(node):
    yield node
    for child in node.children:
        if isinstance(child, _Node):
            yield from _walk(child)


def _find(node, *, tag=None, cls=None, ident=None):
    return [item for item in _walk(node)
            if (tag is None or item.tag == tag)
            and (cls is None or cls in item.attrs.get("class", "").split())
            and (ident is None or item.attrs.get("id") == ident)]


def _one(nodes, label):
    if len(nodes) != 1 or not nodes[0].closed:
        raise ValueError("Peplink lacks one complete " + label + ".")
    return nodes[0]


def _text(node):
    if node.tag in {"script", "style", "form", "template", "noscript"}:
        return ""
    return " ".join(" ".join(_text(c) if isinstance(c, _Node) else c
                             for c in node.children).split())


def _inventory(client):
    response = client.get(SOURCE)
    if not isinstance(response, HTTPResponse):
        raise ValueError("Peplink returned an invalid transport response.")
    if response.status != 200:
        raise FetchError("blocked" if response.status in {401, 403, 429} else "partial",
                         f"Peplink public careers page HTTP {response.status}.")
    dom = _DOM(response.body.decode("utf-8"))
    title = _text(_one(_find(dom.root, tag="title"), "page title"))
    if "peplink" not in title.casefold() or "career" not in title.casefold():
        raise ValueError("Peplink employer careers identity is missing.")
    section = _one(_find(dom.root, tag="section", ident="jobs"), "opportunities section")
    listing = _one(_find(section, cls="jobs-list"), "jobs list")
    cards = _find(listing, cls="jobs-card")
    overlays = _find(listing, cls="overlay")
    if not cards or len(cards) > 1000 or len(cards) != len(overlays):
        raise ValueError("Peplink job cards and full detail panels do not reconcile.")
    if len(_find(dom.root, cls="jobs-card")) != len(cards) or len(_find(dom.root, cls="overlay")) != len(overlays):
        raise ValueError("Peplink publishes job content outside the verified complete list.")
    panels = {}
    for panel in overlays:
        ident = panel.attrs.get("id", "")
        if not re.fullmatch(r"job-overlay-[0-9]+", ident) or ident in panels or not panel.closed:
            raise ValueError("Peplink detail panel identity is missing or repeated.")
        panels[ident] = panel
    out, used = {}, set()
    for card in cards:
        if not card.closed:
            raise ValueError("Peplink job card is truncated.")
        heading = _text(_one(_find(card, tag="h3"), "job card title"))
        location = _text(_one(_find(card, cls="jobs-location"), "job card location"))
        button = _one(_find(card, tag="button", cls="open-overlay"), "job detail button")
        target = button.attrs.get("data-overlay", "")
        ident = target[1:] if target.startswith("#") else ""
        if ident not in panels or ident in used or not heading or not location:
            raise ValueError("Peplink job card has no unique matching detail panel.")
        used.add(ident)
        panel = panels[ident]
        if _text(_one(_find(panel, tag="h3"), "detail title")) != heading or _text(
                _one(_find(panel, cls="jobs-location"), "detail location")) != location:
            raise ValueError("Peplink job card/detail title or location disagrees.")
        blocks = _find(panel, cls="overlay-card-content")
        sections = {}
        for block in blocks:
            label = _text(_one(_find(block, tag="h4"), "description heading"))
            if label in sections or label not in {"Responsibilities", "Requirements"} or not block.closed:
                raise ValueError("Peplink full description sections are missing or changed.")
            items = _find(_one(_find(block, tag="ul"), "full description list"), tag="li")
            if not items or any(not item.closed or not _text(item) for item in items):
                raise ValueError("Peplink description contains missing or truncated items.")
            sections[label] = label + "\n" + "\n".join(_text(item) for item in items)
        if set(sections) != {"Responsibilities", "Requirements"}:
            raise ValueError("Peplink requires the full responsibilities and requirements.")
        key = sha256(heading.casefold().encode()).hexdigest()[:24]
        if key in out:
            raise ValueError("Peplink repeats a job title/identity.")
        # History canonicalizes away fragments. The stable title identity in
        # the harmless page query keeps separate roles from sharing one URL,
        # even if the employer renumbers its presentation-only overlay IDs.
        out[key] = {"title": heading, "location": location, "url": SOURCE + "?position=" + key + "#" + ident,
                    "req_id": ident, "description": sections["Responsibilities"] + "\n\n" + sections["Requirements"]}
    if used != set(panels):
        raise ValueError("Peplink has an unaccounted detail panel.")
    return out


def fetch_peplink(url, company_id, company, transport=None):
    if url != SOURCE or company_id != "COMP-0149" or company.strip().casefold() != "peplink":
        return Inventory("unsupported", reason="Peplink requires its verified employer careers source.", source_url=url, ats="Peplink careers")
    client = transport or CareersTransport()
    try:
        first = _inventory(client)
        if _inventory(client) != first:
            raise ValueError("Peplink complete inventory changed during the scan.")
        rows = []
        for ident, data in first.items():
            row = _base({"id": ident}, "Peplink careers", company_id, company)
            row.update(data)
            rows.append(row)
        return Inventory("complete", rows, f"Peplink: retrieved {len(rows)} full job panels and rechecked the complete page.", SOURCE, "Peplink careers")
    except FetchError as exc:
        return Inventory(exc.status, reason=exc.reason, source_url=SOURCE, ats="Peplink careers")
    except (ValueError, TypeError, AttributeError, RecursionError) as exc:
        return Inventory("partial", reason="Peplink full inventory verification failed: " + str(exc), source_url=SOURCE, ats="Peplink careers")
