"""Independent endpoint mode/limit invariants without inference or networking."""
import importlib.util,sys,types,unittest
from pathlib import Path
from unittest.mock import Mock,patch

class ReasoningBoundaries(unittest.TestCase):
    def setUp(self):
        self.profile=types.SimpleNamespace(context_tokens=12288,temperature=0.1)
        self.estimate=Mock(return_value=types.SimpleNamespace(available_generation_tokens=4096))
        self.require=Mock()
        self.resolve=Mock(return_value=self.profile)
        self.native=Mock(return_value=({'role':'assistant','content':'','tool_calls':[],'thinking':'SECRET_PRIVATE_REASONING'}, {'done_reason':'stop','prompt_eval_count':100,'eval_count':25,'thinking':'PRIVATE'}))
        modules={'context_budget':types.SimpleNamespace(estimate_context=self.estimate,require_output_room=self.require),
                 'profile_policy':types.SimpleNamespace(resolve_profile=self.resolve),'tool_runtime':types.SimpleNamespace(native_turn=self.native)}
        self.patch=patch.dict(sys.modules,modules);self.patch.start();self.addCleanup(self.patch.stop)
        path=Path(__file__).resolve().parents[1]/'wrapper_inference.py'
        spec=importlib.util.spec_from_file_location('independent_wrapper',path);self.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.module)
        self.data={'messages':[{'role':'user','content':'Propose a bounded edit'}],'tools':[{'type':'function','function':{'name':'code_edit'}}],'max_tokens':3072}
        self.engine=object()

    def test_default_false_and_explicit_true_reach_same_engine_profile_and_reservation(self):
        for optional,expected in [({},False),({'think':False},False),({'think':True},True)]:
            self.native.reset_mock();self.require.reset_mock()
            result=self.module.infer(self.engine,dict(self.data,**optional))
            self.assertEqual(self.estimate.call_args.kwargs['thinking'],expected)
            self.assertTrue(self.estimate.call_args.kwargs['internal_tools'])
            self.assertIs(self.native.call_args.args[0],self.engine)
            self.assertIs(self.native.call_args.args[3],self.profile)
            self.assertEqual(self.native.call_args.args[4],3072)
            self.assertIs(self.native.call_args.args[6],expected)
            self.assertIs(self.native.call_args.kwargs['foreground'],False)
            self.require.assert_called_once_with(self.estimate.return_value,3072)
            self.resolve.assert_called_with('qwen-wrapper:4b')
            self.assertEqual(result['context_tokens'],12288)
            self.assertNotIn('SECRET',str(result));self.assertNotIn('thinking',str(result))

    def test_non_bool_modes_reject_before_inference(self):
        for value in (None,0,1,'true','false',[],{}):
            with self.subTest(value=value),self.assertRaises(ValueError):self.module.infer(self.engine,dict(self.data,think=value))
        self.native.assert_not_called()

    def test_context_reservation_failure_never_dispatches(self):
        self.require.side_effect=ValueError('insufficient context')
        with self.assertRaises(ValueError):self.module.infer(self.engine,dict(self.data,think=True))
        self.native.assert_not_called()

    def test_limits_extra_fields_and_unsupported_tools_still_reject(self):
        invalid=[dict(self.data,max_tokens=3073),dict(self.data,max_tokens=True),dict(self.data,model='other'),dict(self.data,execute_tools=True),dict(self.data,tools=[{'function':{'name':'shell'}}])]
        for data in invalid:
            with self.subTest(data=data),self.assertRaises(ValueError):self.module.infer(self.engine,data)
        self.native.assert_not_called()

if __name__=='__main__':unittest.main()
