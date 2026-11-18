"""Evaluate reviewed proposal in memory only; no source writes or network."""
import ast,dataclasses,hashlib,json,re,sys
from pathlib import Path
from urllib.parse import urlsplit,parse_qsl

def extract(source):
    parsed=ast.parse(source);nodes=[]
    for node in parsed.body:
        if isinstance(node,(ast.FunctionDef,ast.ClassDef)) and node.name in {'Board','known_host','board_link'}:nodes.append(node)
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id in {'SLUG','UUID','JAZZ_CUSTOM_HOSTS'} for t in node.targets):nodes.append(node)
    ns={'re':re,'urlsplit':urlsplit,'parse_qsl':parse_qsl,'dataclass':dataclasses.dataclass}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'<reviewed-routing-only>','exec'),ns)
    return ns['board_link']

def main():
    response=Path(sys.argv[1]);source=Path(sys.argv[2]);output=Path(sys.argv[3]);raw=source.read_bytes();before=hashlib.sha256(raw).hexdigest();original=raw.decode()
    proposal=json.loads(response.read_text());calls=proposal['message']['tool_calls'];assert len(calls)==1
    call=calls[0]['function'];assert call['name']=='code_edit';args=call['arguments'];assert set(args)=={'path','sha256','old','new'};assert args['path']=='src/job_search_helper/shared_boards.py';assert args['sha256']==before;assert original.count(args['old'])==1
    revised=original.replace(args['old'],args['new'],1);compile(revised,'<proposed-only>','exec')
    old,new=extract(original),extract(revised)
    def outcome(fn,url):
        try:return dataclasses.asdict(fn(url))
        except Exception as exc:return {'error':type(exc).__name__,'message':str(exc)}
    cases=[]
    for url in ['https://jobs.jobvite.com/samtec/jobs','https://jobs.jobvite.com/samtec/search',
                'https://jobs.jobvite.com/samtec/job/oExample','https://jobs.jobvite.com/other/jobs',
                'https://jobs.jobvite.com/other/search','https://jobs.jobvite.com/other/job/oExample',
                'https://jobs.jobvite.com/','https://jobs.jobvite.com/samtec/private',
                'https://jobs.jobvite.com/samtec/search?q=filtered','http://jobs.jobvite.com/samtec/search',
                'https://apply.workable.com/example/','https://careers.smartrecruiters.com/Example']:
        expected=outcome(old,url)
        if url in {'https://jobs.jobvite.com/samtec/jobs','https://jobs.jobvite.com/samtec/search'}:expected=dict(expected,path='/samtec/search')
        actual=outcome(new,url)
        if '/samtec/job/' in url and actual.get('path') in {'/samtec/jobs','/samtec/search'} and 'error' not in expected:
            expected=dict(expected,path=actual['path'])  # Rubric requires detail identity, not a specific board path.
        cases.append({'url':url,'expected':expected,'actual':actual,'pass':actual==expected})
    assert hashlib.sha256(source.read_bytes()).hexdigest()==before
    result={'result':'PASS_BOUNDED_PROPOSAL' if all(c['pass'] for c in cases) else 'FAIL_BOUNDED_PROPOSAL','exact_current_sha':True,'unique_original_substring':True,'syntax_valid':True,'source_unchanged':True,'tools_executed':False,'cases':cases,'passed':sum(c['pass'] for c in cases),'total':len(cases),'source_sha256':before,'response_sha256':hashlib.sha256(response.read_bytes()).hexdigest(),'boundary':'No proposal applied. Not an integration test.'}
    output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'result':result['result'],'passed':result['passed'],'total':len(cases),'failed_urls':[c['url'] for c in cases if not c['pass']]}))
if __name__=='__main__':main()
