"""Particle-by-Digi attribution on Digi's public UKG board.

Particle moved from its legacy Rippling board to Digi International's
employer-scoped UKG board after the acquisition.  The board is shared by Digi
and the Particle business unit, so this adapter exhaustively scans the board
and attributes a posting only when a structured employer/brand field or the
documented public legal-entity wording identifies Particle by Digi.
"""
from __future__ import annotations

import re

from .ats import FetchError, Inventory, _base, text
from .ukg import (_board, _embedded, _listing, _locations, _criteria,
                  _compensation, _response, resolve_ukg)

BOARD = "https://recruiting2.ultipro.com/DIG1008DIGI/JobBoard/bf7d79dc-5bb9-447e-be77-bc5713185792"
_PARTICLE = re.compile(r"\bparticle(?:\s+by\s+digi)?\b", re.I)
_PARTICLE_BY_DIGI = re.compile(r"\bparticle\s+by\s+digi\b", re.I)
_BRAND_KEYS = {
    "company", "companyname", "brand", "brandname", "businessunit",
    "businessunitname", "employer", "employername", "entity", "entityname",
    "legalentity", "legalentityname", "organization", "organizationname",
}


def _fields(job):
    values = []
    for key, value in job.items():
        norm = re.sub(r"[^a-z]", "", str(key).casefold())
        if norm in _BRAND_KEYS and isinstance(value, (str, int)):
            values.append(str(value).strip())
    return values


def _is_particle(entry, job):
    fields = _fields(job)
    if fields:
        return any(_PARTICLE.search(v) for v in fields), "structured employer/brand field"
    # Digi's official public detail pages document the legal-entity mapping in
    # the posting body ("Particle by Digi").  A bare product mention is not
    # sufficient because Digi-only postings can mention Particle as a product.
    body = " ".join(str(job.get(k) or "") for k in ("Title", "Description", "JobCategoryName"))
    return bool(_PARTICLE_BY_DIGI.search(body)), "documented Particle-by-Digi legal-entity wording"


def _posting_particle(transport, source, entry, company_id, company):
    ident = entry["Id"].lower()
    url = source + "/OpportunityDetail?opportunityId=" + ident
    html = _response(transport.get(url), True)
    job = _embedded(html, r"\bvar\s+opportunity\s*=\s*new\s+US\.Opportunity\.CandidateOpportunityDetail\(\s*")
    if (not isinstance(job, dict) or str(job.get("Id", "")).lower() != ident
            or text(job.get("Title")) != text(entry["Title"])
            or job.get("RequisitionNumber") != entry["RequisitionNumber"]
            or job.get("OpportunityIsClosed") is not False
            or job.get("PublishingStatus") != 1
            or not isinstance(job.get("Description"), str)
            or not text(job["Description"]).strip()):
        raise FetchError("partial", "UKG Particle detail identity, open state, or full description disagrees with listing.")
    memberships = job.get("JobBoardMemberships")
    board_id = source.rsplit("/", 1)[1]
    matching = [m for m in memberships or [] if str(m.get("JobBoardId", "")).lower() == board_id.lower()
                and m.get("PublishedExternal") is True]
    if len(matching) != 1 or matching[0].get("ExternalPostedDate") != entry.get("PostedDate"):
        raise FetchError("partial", "UKG Particle posting is not externally published on the configured board.")
    particle, mode = _is_particle(entry, job)
    if not particle:
        return None, mode
    sections = [text(job["Description"]), *_criteria(job)]
    for field in ("TravelDescription", "EqualOpportunityEmployerDescription", "PayTransparencyPolicyStatement"):
        if job.get(field): sections.append(text(job[field]))
    row = _base({"id": ident}, "UKG", company_id, company)
    row.update(req_id=job["RequisitionNumber"], title=text(job["Title"]), url=url,
               description="\n\n".join(sections), location=_locations(job),
               work_arrangement={0: "Hybrid", 1: "On-site", 2: "Remote"}.get(job.get("JobLocationType"), ""),
               compensation=_compensation(job), department=text(job.get("JobCategoryName")),
               created_at=matching[0].get("ExternalPostedDate") or "", updated_at=job.get("UpdatedDate") or "")
    row["attribution"] = mode
    return row, mode


def fetch_particle(ats, url, company_id, company, transport=None):
    jobs, source, context = [], url, "Particle UKG board"
    try:
        _, board, root = resolve_ukg(ats, url)
        source = root + board
        scope = _board(transport, source)
        entries = _listing(transport, source)
        seen = set()
        for entry in entries:
            context = "Particle detail " + entry["Id"]
            row, _ = _posting_particle(transport, source, entry, company_id, company)
            if row is not None:
                if row["posting_id"] in seen or row["url"] in {j["url"] for j in jobs}:
                    raise FetchError("partial", "Particle attribution produced a duplicate provider ID or canonical URL.")
                seen.add(row["posting_id"]); jobs.append(row)
        if _listing(transport, source) != entries or _board(transport, source) != scope:
            raise FetchError("partial", "Digi UKG inventory or board scope changed during Particle attribution.")
        return Inventory("complete", jobs, f"Particle: exhaustively scanned {len(entries)} Digi postings and attributed {len(jobs)} Particle postings.", source, "UKG")
    except FetchError as e:
        return Inventory("blocked" if e.status == "blocked" else ("partial" if jobs else e.status), jobs, context + ": " + e.reason, source, "UKG")
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return Inventory("partial" if jobs else "failed", jobs, context + ": network or malformed UKG data; Particle inventory incomplete.", source, "UKG")
