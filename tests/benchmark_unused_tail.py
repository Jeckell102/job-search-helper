"""Synthetic API-response comparison; no network or credentials."""
import json
from job_search_helper.repository import GoogleRepository
from job_search_helper.sheet_profile import COMPACT_SCHEMAS
from sheets_fixture import RangeSheets
existing, unused, batch = 200, 23829, 100
rows = {'Job History': [{'Job Key': f'job-{i}', 'Company': 'Acme',
    'Official Job URL': f'https://example.test/jobs/{i}'} for i in range(existing)]}
service = RangeSheets(rows, schemas=COMPACT_SCHEMAS)
sheet = service.sheet('Job History')
sheet['properties']['gridProperties']['rowCount'] = existing + 1 + unused
rules = {
    'Added to Opportunities?': ['Yes','No','Pending','Manual Review'],
    'Job Status': ['Open and verified','Closed','Unable to verify','Not verified'],
    'Review Status': ['Needs Review','In Progress','Reviewed','Manual Review'],
    'Fit Level': ['Strong','Possible','Stretch'],
}
for row in range(existing+1,existing+1+unused):
    for header, choices in rules.items():
        service.set_cell('Job History',row,header,cell={'dataValidation':{'strict':True,'showCustomUi':True,
            'condition':{'type':'ONE_OF_LIST','values':[{'userEnteredValue':v} for v in choices]}}})
repo=GoogleRepository(service,'fixture',schemas=COMPACT_SCHEMAS,min_request_interval=0)
results=[]
for phase in ('cold','warm'):
    before=dict(repo.metrics)
    ops=[{'tab':'Job History','identity':{'Job Key':f'{phase}-{i}'},
        'values':{'Company':'Acme','Official Job URL':f'https://example.test/jobs/{phase}-{i}'},
        'append_if_missing':True} for i in range(batch)]
    result=repo.commit(ops)
    results.append({'phase':phase,'inserted':result['inserted'],
        **{key:repo.metrics[key]-before[key] for key in ('read_requests','write_requests','read_response_bytes')}})
print(json.dumps({'existing_rows':existing,'unused_rows':unused,'batch_rows':batch,'results':results},indent=2))
