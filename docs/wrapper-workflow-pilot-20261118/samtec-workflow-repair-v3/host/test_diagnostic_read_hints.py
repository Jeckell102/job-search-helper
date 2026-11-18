import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
import coordinator_evidence as e
import coordinator_workflow as w

class RelevantReadTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.path='src/job_search_helper/shared.py'
        text='\n'*110+'def resolve():\n    provider="ProviderX"\n    return "/featured"\n'+'\n'*440+'def listing():\n    raise ValueError("No verified list; empty inventory unproven.")\n'+'\n'*100
        p=self.root/self.path;p.parent.mkdir(parents=True);p.write_text(text)
        doc=self.root/'docs/backlog/COMP-1234.md';doc.parent.mkdir(parents=True);doc.write_text('**Configured source:** `ProviderX` — https://jobs.example/widget\n**Exact recorded reason:** No verified list; empty inventory unproven.\n')
        self.req={'required_files':[self.path,'docs/backlog/COMP-1234.md'],'read_hints':{self.path:[650]},'source_targets':[]}
        self.manifest={self.path:hashlib.sha256(p.read_bytes()).hexdigest()}
    def test_exact_diagnostic_and_provider_literals_precede_irrelevant_hint(self):
        hints=e.diagnostic_read_hints(self.req,self.root)[self.path]
        self.assertEqual(hints[:2],[547,104])
        steps=w.file_steps(self.req,self.root)
        self.assertEqual([x[1] for x in steps if x[0]==self.path][:2],hints[:2])
    def test_implementation_collects_missing_guard_without_mutating_scope(self):
        state={'phase':'implement','evidence_requirements':self.req,'workflow':{}}
        before=copy.deepcopy(state)
        plan=w.plan(state,[],self.manifest,self.root)
        self.assertEqual(plan['next']['arguments'],{'path':self.path,'start_line':547})
        self.assertEqual(state,before)
        text=(self.root/self.path).read_text().splitlines()
        receipt={'id':1,'phase':'inspect','name':'code_read','arguments':{'path':self.path,'start_line':1},'result':{'ok':True,'result':{'sha256':self.manifest[self.path],'text':'\n'.join(f'{i}: {line}' for i,line in enumerate(text,1))}}}
        plan=w.plan(state,[receipt],self.manifest,self.root)
        self.assertEqual(plan['next']['arguments']['start_line'],1) # normal implementation read, no diagnostic rereads
    def test_unassigned_docs_and_code_never_expand_scope(self):
        req={'required_files':[self.path],'read_hints':{self.path:[1]}}
        self.assertEqual(e.diagnostic_read_hints(req,self.root),{})

if __name__=='__main__':unittest.main()
