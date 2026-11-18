import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

class ThinkingTests(unittest.TestCase):
    def setUp(self):
        self.profile=SimpleNamespace(context_tokens=12288,temperature=0.2,model_id='qwen-wrapper:4b',think=False)
        self.estimate=Mock(return_value=object());self.require=Mock()
        self.native=Mock(return_value=({'role':'assistant','content':'','tool_calls':[], 'thinking':'private value'}, {'done_reason':'stop','prompt_eval_count':17,'eval_count':27}))
        modules={}
        for name,fields in {'context_budget':{'estimate_context':self.estimate,'require_output_room':self.require},'profile_policy':{'resolve_profile':Mock(return_value=self.profile)},'tool_runtime':{'native_turn':self.native}}.items():
            module=ModuleType(name)
            for key,value in fields.items():setattr(module,key,value)
            modules[name]=module
        with patch.dict(sys.modules,modules):
            spec=importlib.util.spec_from_file_location('isolated_wrapper',Path(__file__).with_name('wrapper_inference.py'));self.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.module)
        self.engine=object();self.data={'messages':[{'role':'user','content':'propose patch'}],'tools':[{'type':'function','function':{'name':'code_edit'}}],'max_tokens':3072}
    def test_default_false_and_explicit_flags_use_same_estimator_and_native_mode(self):
        for supplied in ('absent',False,True):
            data=dict(self.data)
            if supplied!='absent':data['think']=supplied
            result=self.module.infer(self.engine,data)
            expected=False if supplied=='absent' else supplied
            self.assertIs(self.estimate.call_args.kwargs['thinking'],expected)
            self.assertIs(self.native.call_args.args[6],expected)
            self.assertIs(self.native.call_args.args[0],self.engine)
            self.assertEqual(self.native.call_args.args[3].model_id,'qwen-wrapper:4b')
            self.assertEqual(result['context_tokens'],12288)
            self.assertEqual(self.native.call_args.kwargs,{'foreground':False})
    def test_invalid_types_missing_and_unknown_keys_reject_before_inference(self):
        invalid=[dict(self.data,think=x) for x in (None,0,1,'true',[],{})]
        invalid += [dict(self.data,extra=True),{'tools':[],'max_tokens':1},[]]
        for data in invalid:
            with self.subTest(data=data),self.assertRaises(ValueError):self.module.infer(self.engine,data)
        self.native.assert_not_called()
    def test_private_thinking_never_returned_but_all_output_usage_retained(self):
        result=self.module.infer(self.engine,dict(self.data,think=True))
        self.assertNotIn('thinking',result['message']);self.assertNotIn('private value',str(result))
        self.assertEqual(result['usage']['eval_count'],27)
    def test_output_context_and_tool_schema_limits_unchanged(self):
        for change in ({'max_tokens':3073},{'max_tokens':True},{'tools':[{'function':{'name':'shell'}}]}):
            with self.assertRaises(ValueError):self.module.infer(self.engine,dict(self.data,**change))
        self.native.assert_not_called()
        self.require.side_effect=ValueError('no output room')
        with self.assertRaises(ValueError):self.module.infer(self.engine,dict(self.data,think=True))
        self.native.assert_not_called()

if __name__=='__main__':unittest.main()
