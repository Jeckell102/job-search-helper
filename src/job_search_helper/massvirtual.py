"""Mass Virtual's official Paylocity JSON feed embedded in its open-positions page."""
from __future__ import annotations
import json
from .ats import FetchError, Inventory, _base, text
SOURCE="https://recruiting.paylocity.com/recruiting/v2/api/feed/jobs/2df5ac23-47b5-4c64-b536-e7f04caf6ffe"

def _read(client):
 r=client.get(SOURCE)
 if r.status in (401,403,429): raise FetchError("blocked",f"Mass Virtual Paylocity feed HTTP {r.status}.")
 if r.status!=200: raise FetchError("partial",f"Mass Virtual Paylocity feed HTTP {r.status}.")
 try: d=json.loads(r.body.decode("utf-8"))
 except (UnicodeDecodeError,json.JSONDecodeError): raise FetchError("partial","Mass Virtual feed was not valid JSON.")
 if not isinstance(d,dict) or not isinstance(d.get("jobs"),list): raise FetchError("partial","Mass Virtual feed schema lacks jobs list.")
 return d["jobs"]

def _parse(rows):
 out=[]; seen=set()
 for item in rows:
  if not isinstance(item,dict) or type(item.get("jobId")) is not int or item["jobId"]<=0: raise FetchError("partial","Mass Virtual feed contains malformed job ID.")
  ident=str(item["jobId"])
  if ident in seen: raise FetchError("partial","Mass Virtual feed repeats a job ID.")
  seen.add(ident)
  if item.get("companyName") not in {"Mass Virtual, Inc.","Mass Virtual Inc.","Mass Virtual"}: raise FetchError("partial","Mass Virtual feed contains a foreign employer record.")
  title=text(item.get("title")); desc=text(item.get("description")); url=item.get("displayUrl")
  if not title or len(desc)<500 or not isinstance(url,str) or not url.startswith("https://recruiting.paylocity.com/recruiting/jobs/Details/"): raise FetchError("partial","Mass Virtual feed contains an incomplete posting.")
  row=_base({"id":ident},"Mass Virtual Paylocity","COMP-0344","Mass Virtual")
  row.update(title=title,description=desc,url=url,location=text(item.get("jobLocation")),date_posted=text(item.get("publishedDate")))
  out.append(row)
 if not out: raise FetchError("partial","Mass Virtual feed contained no verifiable postings.")
 return sorted(out,key=lambda j:j["posting_id"])

def fetch_massvirtual(careers_url,company_id,company,transport=None):
 from .discovery import CareersTransport
 if company_id!="COMP-0344" or company.casefold()!="mass virtual" or careers_url.rstrip("/") not in {"https://www.massvirtual.com/careers","https://www.massvirtual.com/career",SOURCE}:
  return Inventory("unsupported",reason="Mass Virtual requires its verified official Paylocity feed.",source_url=careers_url,ats="Mass Virtual Paylocity")
 client=transport or CareersTransport(); jobs=[]
 try:
  first=_parse(_read(client)); jobs=first; second=_parse(_read(client))
  if {j["posting_id"] for j in first}!={j["posting_id"] for j in second}: raise FetchError("partial","Mass Virtual feed changed during scan.")
  return Inventory("complete",jobs,f"Mass Virtual: retrieved {len(jobs)} full postings and rechecked the public feed.",SOURCE,"Mass Virtual Paylocity")
 except FetchError as e: return Inventory(e.status if not jobs else "partial",jobs,e.reason,SOURCE,"Mass Virtual Paylocity")
 except (TypeError,ValueError,AttributeError,UnicodeError): return Inventory("partial",jobs,"Mass Virtual feed validation failed.",SOURCE,"Mass Virtual Paylocity")
