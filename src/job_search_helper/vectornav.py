"""VectorNav's official Workable widget and public job detail feed."""
from __future__ import annotations
import json
from .ats import FetchError, HTTPTransport, Inventory, _base, text

SOURCE = "https://apply.workable.com/vectornav/"
WIDGET = "https://apply.workable.com/api/v1/widget/accounts/381771"
DETAIL_ROOT = "https://apply.workable.com/api/v2/accounts/vectornav/jobs/"

def _json(client, url):
    response = client.get(url)
    if response.status != 200:
        raise FetchError("blocked" if response.status in (401, 403, 429) else "partial", "VectorNav public Workable feed was unavailable.")
    try: return json.loads(response.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError): raise FetchError("partial", "VectorNav public Workable feed returned malformed JSON.") from None

def _entries(data):
    if not isinstance(data, dict) or data.get("name") != "VectorNav Technologies" or not isinstance(data.get("jobs"), list):
        raise FetchError("partial", "VectorNav Workable account scope or schema was invalid.")
    out=[]; seen=set()
    for item in data["jobs"]:
        if not isinstance(item, dict) or not isinstance(item.get("shortcode"), str) or not item["shortcode"] or item["shortcode"] in seen:
            raise FetchError("partial", "VectorNav Workable inventory contained an invalid or duplicate posting.")
        if item.get("isInternal") is True:
            raise FetchError("partial", "VectorNav Workable inventory contained an unpublished or internal posting.")
        seen.add(item["shortcode"]); out.append(item)
    return out

def fetch_vectornav(url, company_id, company, transport=None):
    if url != SOURCE:
        return Inventory("unsupported", reason="VectorNav requires its verified Workable board.", source_url=url, ats="Workable")
    client=transport or HTTPTransport(); jobs=[]
    try:
        entries=_entries(_json(client,WIDGET))
        for entry in entries:
            ident=entry["shortcode"]; detail=_json(client,DETAIL_ROOT+ident)
            if (not isinstance(detail,dict) or detail.get("shortcode")!=ident or detail.get("title")!=entry.get("title") or detail.get("state")!="published" or not text(detail.get("description"))):
                raise FetchError("partial", "VectorNav Workable detail identity or full description was invalid.")
            locs=entry.get("locations") or []
            location="; ".join(dict.fromkeys(text(x.get("city"))+((", "+text(x.get("region"))) if text(x.get("region")) else "") for x in locs if isinstance(x,dict) and text(x.get("city"))))
            row=_base({"id":ident},"Workable",company_id,company)
            row.update(title=text(entry.get("title")),url="https://apply.workable.com/vectornav/j/"+ident+"/",description="\n\n".join(text(detail.get(k)) for k in ("description","requirements","benefits") if detail.get(k)),req_id=text(entry.get("code")),location=location,created_at=text(detail.get("published") or entry.get("published_on")),work_arrangement=text(detail.get("workplace") or ("Remote" if entry.get("telecommuting") else "")))
            if not row["title"] or len(row["description"])<100: raise FetchError("partial", "VectorNav Workable detail lacked a full posting body.")
            jobs.append(row)
        check=_entries(_json(client,WIDGET))
        if {(x.get("shortcode"),x.get("title")) for x in check}!={(x.get("shortcode"),x.get("title")) for x in entries}: raise FetchError("partial", "VectorNav Workable inventory changed during the scan.")
        return Inventory("complete",jobs,f"VectorNav: retrieved {len(jobs)} complete Workable postings and rechecked the public inventory.",SOURCE,"Workable")
    except FetchError as error: return Inventory(error.status if not jobs else "partial",jobs,error.reason,SOURCE,"Workable")
    except (AttributeError,KeyError,TypeError,ValueError): return Inventory("partial",jobs,"VectorNav Workable schema validation failed.",SOURCE,"Workable")
