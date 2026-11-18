"""Bounded corrective steering without weakening evidence or budget gates."""
import json
import unittest
import coordinator as c
import test_coordinator as f
import test_coordinator_workflow as wf

class ProgressCorrectionTests(unittest.TestCase):
    setUp = wf.WorkflowTests.setUp
    task = wf.WorkflowTests.task
    collect = wf.WorkflowTests.collect
    checkpoint = f.CoordinatorTests.checkpoint

    def test_one_corrective_instruction_precedes_final_stall_stop(self):
        task = self.task()
        self.collect(task)
        read = f.response('code_read', {'path':'src/a.py', 'start_line':1})
        self.answers = [read, read, self.checkpoint()]
        self.co.step(task)
        state = self.co.store.get(task)
        self.assertEqual(state['workflow']['corrected_phases'], ['inspect'])
        self.assertIn('single corrective', state['workflow']['progress_instruction'])
        before = (state['calls'], state['tokens'], len(self.co.store.receipts(task)))
        self.answers = [read]
        self.co.step(task)
        after = self.co.store.get(task)
        self.assertEqual(after['status'], 'PAUSED_BLOCKED')
        self.assertEqual(after['workflow']['corrected_phases'], ['inspect'])
        self.assertEqual(after['calls'], before[0]+1)
        self.assertGreater(after['tokens'], before[1])
        self.assertEqual(len(self.co.store.receipts(task)), before[2])
        self.assertIn('progress_instruction', json.loads(self.history[-1][1]['content']))

    def test_inspect_can_finish_without_edit_but_implementation_gate_remains(self):
        task = self.task('develop')
        self.collect(task)
        self.answers = [self.checkpoint('phase_done')]
        self.co.step(task)
        self.assertEqual(self.co.store.get(task)['phase'], 'implement')
        system = self.history[-1][0]['content']
        self.assertIn('In implement only', system)
        self.assertIn('Inspection requires no edit', system)
        self.co.step(task)
        self.answers = [self.checkpoint('phase_done')]
        self.co.step(task)
        self.co.step(task)
        self.assertEqual(self.co.store.get(task)['status'], 'PAUSED_BLOCKED')
        self.assertIn('No development change exists', self.co.store.get(task)['reason'])

if __name__ == '__main__': unittest.main()
