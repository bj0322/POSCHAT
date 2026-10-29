# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
"""동시 세션의 실행·출력·승인·중지를 실제 Bridge에서 확인한다."""
import threading
import time
import unittest
from unittest.mock import patch

from test_code_agent import CodeAgentTests
import agent
import storage


class SessionTests(unittest.TestCase):
    setUp = CodeAgentTests.setUp
    push = CodeAgentTests.push

    def wait_for(self, predicate):
        end = time.monotonic() + 5
        while not predicate() and time.monotonic() < end:
            time.sleep(0.01)
        self.assertTrue(predicate())

    def test_chats_keep_running_and_stop_independently(self):
        entered = {x: threading.Event() for x in ('a', 'b')}
        release = threading.Event()
        self.addCleanup(release.set)
        self.addCleanup(self.bridge.stop)

        def run(worker, history, task, *args):
            entered[task].set()
            release.wait(5)
            worker.on_delta(task + ' 출력')
            return task + ' 답변'

        a, b = (self.bridge.new_thread()['id'] for _ in range(2))
        with patch.object(agent.Agent, 'run', run):
            self.assertTrue(self.bridge.send(a, 'a', False)['ok'])
            self.assertTrue(self.bridge.send(b, 'b', False)['ok'])
            self.assertTrue(entered['a'].wait(3))
            self.assertTrue(entered['b'].wait(3))
            self.assertEqual(set(self.bridge.get_state()['running_threads']), {a, b})
            self.assertFalse(self.bridge.send(a, '중복', False)['ok'])
            self.bridge.stop(a)
            self.assertFalse(self.bridge._chat_runs[b]['cancel'].is_set())
            release.set()
            self.wait_for(lambda: not self.bridge._chat_runs)
        self.assertFalse(any(m['role'] == 'assistant' for m in storage.load_thread(a)['messages']))
        self.assertEqual(storage.load_thread(b)['messages'][-1]['content'], 'b 답변')
        self.assertTrue(any(e.get('thread_id') == b and e.get('text') == 'b 출력' for e in self.events))

    def test_code_tasks_run_with_chat_and_control_the_selected_task(self):
        release = threading.Event()
        self.addCleanup(release.set)
        self.addCleanup(self.bridge._ca_shutdown)
        started = []

        def run(worker, history, task, *args):
            started.append(task)
            release.wait(5)
            return task + ' 완료'

        chat = self.bridge.new_thread()['id']
        with patch.object(agent.Agent, 'run', run):
            self.assertTrue(self.bridge.send(chat, '채팅', False)['ok'])
            first = self.bridge.code_agent_start('첫 작업')
            second = self.bridge.code_agent_start('둘째 작업')
            self.assertTrue(first['ok'], first)
            self.assertTrue(second['ok'], second)
            a, b = first['task']['id'], second['task']['id']
            self.wait_for(lambda: len(started) == 3)
            self.assertEqual(set(self.bridge.code_agent_state()['running_tasks']), {a, b})
            self.assertFalse(self.bridge.code_agent_start('중복', a)['ok'])
            self.assertTrue(self.bridge.code_agent_steer('둘째 지시', b)['ok'])
            self.assertEqual(self.bridge._ca_run(a)['steer'], [])
            self.assertEqual(self.bridge._ca_run(b)['steer'], ['둘째 지시'])
            self.bridge.code_agent_set_approval('plan', b)
            self.assertEqual(self.bridge._ca_run(a)['mode'], 'auto_edit')
            self.assertEqual(self.bridge._ca_run(b)['mode'], 'plan')
            self.bridge.code_agent_stop(a)
            self.assertFalse(self.bridge._ca_run(b)['cancel'].is_set())
            self.assertFalse(self.bridge._chat_runs[chat]['cancel'].is_set())
            release.set()
            self.wait_for(lambda: not self.bridge._ca_runs and not self.bridge._chat_runs)
        self.assertEqual(self.bridge._ca().load(a)['status'], 'stopped')
        self.assertEqual(self.bridge._ca().load(b)['status'], 'done')

    def test_allow_and_cancellation_do_not_cross_chat_sessions(self):
        self.bridge._push = self.events.append
        allow_a, allow_b = set(), set()
        results = {}
        cancelled = threading.Event()
        def confirm(tid, allowed, alive):
            results[tid] = self.bridge._confirm(tid, 'run', '명령', 'echo', alive, allowed)
        workers = [threading.Thread(target=confirm, args=('a', allow_a, lambda: True)),
                   threading.Thread(target=confirm, args=('b', allow_b, lambda: not cancelled.is_set()))]
        for w in workers:
            w.start()
        self.wait_for(lambda: len(self.bridge._pending) == 2)
        a = next(e for e in self.events if e.get('thread_id') == 'a')
        self.bridge.resolve_confirm(a['id'], 'always')
        self.wait_for(lambda: 'a' in results)
        self.assertIn('run', allow_a)
        self.assertNotIn('run', allow_b)
        self.assertNotIn('b', results)
        cancelled.set()
        for w in workers:
            w.join(2)
        self.assertFalse(results['b'])

    def test_initialization_failure_releases_session(self):
        tid = self.bridge.new_thread()['id']
        with patch.object(self.bridge, '_make_engine', side_effect=RuntimeError('초기화 실패')):
            self.assertTrue(self.bridge.send(tid, '질문', False)['ok'])
            self.wait_for(lambda: not self.bridge._chat_runs)
            r = self.bridge.code_agent_start('작업')
            self.assertTrue(r['ok'], r)
            self.wait_for(lambda: not self.bridge._ca_runs)
        self.assertEqual(storage.load_thread(tid)['messages'][-1]['role'], 'error')
        self.assertEqual(self.bridge._ca().load(r['task']['id'])['status'], 'error')

    def test_code_sessions_keep_their_workspace_after_switching(self):
        release = threading.Event()
        self.addCleanup(release.set)
        self.addCleanup(self.bridge._ca_shutdown)
        roots = []
        def run(worker, history, task, *args):
            roots.append(str(worker.workspace))
            release.wait(5)
            return '완료'
        with patch.object(agent.Agent, 'run', run):
            a = self.bridge.code_agent_start('첫 폴더 작업')['task']['id']
            other = self.root / 'other'
            other.mkdir()
            self.bridge._config['workspace'] = str(other)
            self.assertIsNone(self.bridge.code_agent_state()['running'])
            b = self.bridge.code_agent_start('둘째 폴더 작업')['task']['id']
            self.wait_for(lambda: len(roots) == 2)
            self.assertEqual(set(roots), {str(self.ws), str(other)})
            self.assertEqual(self.bridge.code_agent_state()['running'], b)
            self.assertIn(a, self.bridge.code_agent_state()['running_tasks'])
            release.set()
            self.wait_for(lambda: not self.bridge._ca_runs)

    def test_identical_file_proposals_are_owned_by_each_chat(self):
        import code_diff
        p = self.ws / 'calc.py'
        old = p.read_text()
        store = self.bridge._code_store()
        a, created = store.add(code_diff.new_proposal(str(self.ws), 'calc.py', old, old + '# 수정\n', thread_id='a'))
        b, created = store.add(code_diff.new_proposal(str(self.ws), 'calc.py', old, old + '# 수정\n', thread_id='b'))
        self.assertNotEqual(a.proposal_id, b.proposal_id)
        self.bridge._code_finish(a, 'cancelled', 'a 중지')
        self.assertEqual(b.status, 'pending')

    def test_bundled_skills_are_discoverable(self):
        skills = agent.discover_skills('')
        for name in ('ponytail', 'strategic-compact', 'rtk'):
            self.assertEqual(skills[name].source, '내장')
            self.assertTrue(skills[name].description)
            self.assertTrue(skills[name].body)
