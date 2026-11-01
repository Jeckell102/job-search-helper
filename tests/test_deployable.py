import json

from job_search_helper.ats import HTTPResponse
from job_search_helper.deployable import SOURCE, fetch_deployable

CID, COMPANY = "COMP-0302", "Deployable Technologies"
LIST = json.dumps({"max_num_pages": 1, "html": '<li class="post-1 job_listing status-expired"><a href="https://deployabletechnologies.com/?post_type=job_listing&#038;p=1"><h3>Old</h3><strong>Deployable Technologies</strong><div class="location">USA</div></a></li>'})
class T:
    def __init__(self, body=LIST, status=200): self.body,self.status,self.calls=body,status,[]
    def get(self, url): self.calls.append(url); return HTTPResponse(self.status, self.body.encode(), {})

def test_expired_records_produce_verified_zero():
    r=fetch_deployable(SOURCE,CID,COMPANY,T()); assert r.status=="complete"; assert not r.jobs

def test_wrong_identity_and_errors_fail_closed():
    assert fetch_deployable(SOURCE,"OTHER",COMPANY,T()).status=="unsupported"
    assert fetch_deployable(SOURCE,CID,COMPANY,T(status=403)).status=="blocked"
    assert fetch_deployable(SOURCE,CID,COMPANY,T(body="{}" )).status=="partial"
