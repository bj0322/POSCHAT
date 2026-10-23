# SPDX-FileCopyrightText: 2026 Beomjoon Kim
# SPDX-License-Identifier: AGPL-3.0-only
import base64
import queue
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import po_note
import stt


class PoNoteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patch = patch.object(po_note, "NOTES_DIR", Path(self.temp.name) / "po_notes")
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def upload(self, note_id, name, data):
        upload_id = uuid.uuid4().hex
        half = len(data) // 2
        self.assertIsNone(po_note.upload_material(note_id, upload_id, name, 0, base64.b64encode(data[:half]).decode(), False))
        return po_note.upload_material(note_id, upload_id, name, half, base64.b64encode(data[half:]).decode(), True)

    def test_note_keeps_transcript_materials_memo_and_note(self):
        note = po_note.create("선형대수 3주차")
        note_id = note["id"]
        po_note.append_segment(note_id, {"start": 65.2, "end": 70, "text": "고유값은 시험에 나옵니다."})
        po_note.append_segment(note_id, {"start": 3, "end": 5, "text": "오늘은 고유값을 배웁니다."})
        item = self.upload(note_id, "slides.md", "# Eigenvalue\n고유값 분해 Eigendecomposition".encode())
        po_note.save_memo(note_id, "예제 2 다시 보기")

        loaded = po_note.load(note_id)
        self.assertEqual([s["start"] for s in loaded["transcript"]], [3, 65.2])
        self.assertEqual(loaded["materials"][0]["name"], "slides.md")
        self.assertEqual(loaded["memo"], "예제 2 다시 보기")
        self.assertIn("Eigendecomposition", po_note.material_text(note_id, item["id"]))
        self.assertIn("Eigenvalue", po_note.vocabulary(note_id))
        self.assertEqual(po_note.list_notes()[0]["title"], "선형대수 3주차")

        prompts, merge = po_note.build_prompts(note_id)
        self.assertIsNone(merge)
        self.assertEqual(len(prompts), 1)
        prompt = prompts[0][1]
        self.assertIn("[01:05] 고유값은 시험에 나옵니다.", prompt)
        self.assertIn("고유값 분해", prompt)
        self.assertIn("예제 2 다시 보기", prompt)

        seen = []
        text = po_note.generate(note_id, lambda p, d: (seen.append(d), "```markdown\n# 노트\n본문\n```")[1])
        self.assertEqual(text, "# 노트\n본문")
        self.assertEqual(po_note.load(note_id)["note"], "# 노트\n본문")
        self.assertIsNone(seen[0])

        po_note.remove_material(note_id, item["id"])
        self.assertEqual(po_note.load(note_id)["materials"], [])
        po_note.delete(note_id)
        self.assertEqual(po_note.list_notes(), [])

    def test_long_transcript_is_noted_in_parts_then_merged(self):
        note_id = po_note.create("긴 강의")["id"]
        for i in range(400):
            po_note.append_segment(note_id, {"start": i * 10, "end": i * 10 + 9, "text": "설명 " * 40 + str(i)})
        calls = []

        def ask(prompt, on_delta):
            calls.append((prompt, on_delta))
            return f"부분{len(calls)}"

        text = po_note.generate(note_id, ask, on_delta=lambda t: None)
        steps = len(po_note._chunks(po_note.transcript(note_id)))
        self.assertGreater(steps, 1)
        self.assertEqual(len(calls), steps + 1)
        self.assertIn("<부분 1>\n부분1", calls[-1][0])
        self.assertIsNotNone(calls[-1][1])  # 마지막 합치기만 화면에 흘려 보낸다
        self.assertIsNone(calls[0][1])
        self.assertEqual(text, f"부분{steps + 1}")

    def test_rejects_unsupported_files_and_bad_ids(self):
        note_id = po_note.create()["id"]
        with self.assertRaises(po_note.NoteError):
            self.upload(note_id, "lecture.ppt", b"old")
        with self.assertRaises(po_note.NoteError):
            self.upload(note_id, "run.exe", b"MZ")
        with self.assertRaises(po_note.NoteError):
            po_note.load("../../etc")
        with self.assertRaises(po_note.NoteError):
            po_note.build_prompts(note_id)  # 전사도 자료도 없다


class FakeEngine:
    label = "fake"

    def __init__(self, batch=0):
        self.batch_seconds = batch
        self.calls = []

    def transcribe(self, samples, context=""):
        self.calls.append(len(samples))
        return f"구간{len(self.calls)}"


class LiveSessionTranscribeTests(unittest.TestCase):
    def session(self, engine):
        import numpy as np
        out = []
        session = stt.LiveSession(engine, out.append, offset=100)
        session._segmenter = type("S", (), {"_np": np})()
        return session, out, np

    def test_local_engine_transcribes_each_segment(self):
        try:
            session, out, np = self.session(FakeEngine())
        except ImportError:
            self.skipTest("numpy 없음")
        for start in (0, 16000 * 5):
            session._jobs.put((start, np.zeros(16000, dtype=np.float32)))
        session._jobs.put(None)
        session._transcribe()
        self.assertEqual([(s["start"], s["end"], s["text"]) for s in out], [(100.0, 101.0, "구간1"), (105.0, 106.0, "구간2")])

    def test_server_engine_batches_segments_to_save_credits(self):
        try:
            engine = FakeEngine(batch=25)
            session, out, np = self.session(engine)
        except ImportError:
            self.skipTest("numpy 없음")
        for i in range(4):  # 10초 간격의 8초 구간 4개 → 25초까지 모아 두 번 보낸다
            session._jobs.put((i * 16000 * 10, np.zeros(16000 * 8, dtype=np.float32)))
        session._jobs.put(None)
        session._transcribe()
        self.assertEqual(len(engine.calls), 2)
        self.assertEqual((out[0]["start"], out[0]["end"]), (100.0, 128.0))
        self.assertEqual((out[1]["start"], out[1]["end"]), (130.0, 138.0))

    def test_failed_server_segment_falls_back_to_local(self):
        try:
            session, out, np = self.session(FakeEngine())
        except ImportError:
            self.skipTest("numpy 없음")

        class Broken:
            label, batch_seconds = "server", 0

            def transcribe(self, samples, context=""):
                raise stt.SttError("크레딧 부족")

        errors = []
        session.engine, session.fallback, session._on_error = Broken(), FakeEngine(), errors.append
        session._jobs.put((0, np.zeros(1600, dtype=np.float32)))
        session._jobs.put(None)
        session._transcribe()
        self.assertEqual(out[0]["text"], "구간1")
        self.assertIn("크레딧 부족", errors[0])


class FakeLocal:
    label = "local"
    batch_seconds = 0

    def __init__(self, confs):
        self.confs = list(confs)

    def recognize(self, samples):
        return f"초안{len(samples)}", self.confs.pop(0)

    def transcribe(self, samples, context=""):
        return self.recognize(samples)[0]


class FakeRefiner:
    label = "server"

    def __init__(self, result=None, error=None):
        self.calls, self.result, self.error = [], result, error

    def refine(self, samples, drafts, context=""):
        self.calls.append(list(drafts))
        if self.error:
            raise stt.SttError(self.error)
        return self.result(drafts) if callable(self.result) else self.result


class HybridTests(unittest.TestCase):
    def run_session(self, confs, refiner, budget=True, seconds=10):
        try:
            import numpy as np
        except ImportError:
            self.skipTest("numpy 없음")
        segs, refined, notes = [], [], []
        session = stt.LiveSession(FakeLocal(confs), segs.append, on_error=notes.append, refiner=refiner,
                                  on_refine=lambda ids, fixed: refined.append((ids, fixed)),
                                  budget_ok=lambda: budget, id_base=7)
        session._segmenter = type("S", (), {"_np": np})()
        import threading
        t = threading.Thread(target=session._refine_loop)
        t.start()
        for i, _ in enumerate(confs):
            session._jobs.put((i * 16000 * 12, np.zeros(16000 * seconds, dtype=np.float32)))
        session._jobs.put(None)
        session._transcribe()
        t.join(5)
        return session, segs, refined, notes

    def test_local_text_comes_first_and_low_confidence_batches_are_refined(self):
        refiner = FakeRefiner(lambda drafts: [d + "(고침)" for d in drafts])
        # 10초 구간 14개 = 140초: 앞의 12개(120초)가 한 묶음, 나머지 2개가 녹음을 멈출 때의 묶음
        session, segs, refined, _ = self.run_session([0.95] * 5 + [0.6] + [0.95] * 8, refiner)
        self.assertEqual([s["id"] for s in segs], list(range(7, 21)))
        self.assertTrue(all(s["src"] == "local" for s in segs))
        self.assertEqual(len(refiner.calls), 1)  # 두 번째 묶음은 모두 확신해서 서버를 부르지 않는다
        self.assertEqual(refined[0][0], list(range(7, 19)))
        self.assertTrue(refined[0][1][0].endswith("(고침)"))
        self.assertEqual(session.stats["skipped_batches"], 1)

    def test_confident_lecture_uses_no_credits(self):
        refiner = FakeRefiner(lambda drafts: drafts)
        session, segs, refined, _ = self.run_session([0.9, 0.92, 0.88], refiner)
        self.assertEqual(len(segs), 3)
        self.assertEqual(refiner.calls, [])
        self.assertEqual(session.stats["server_calls"], 0)

    def test_budget_guard_and_server_failure_keep_local_text(self):
        refiner = FakeRefiner(lambda drafts: drafts)
        session, segs, refined, notes = self.run_session([0.5, 0.5], refiner, budget=False)
        self.assertEqual(len(segs), 2)
        self.assertEqual(refiner.calls, [])
        self.assertIn("예산", notes[0])

        broken = FakeRefiner(error="504")
        session, segs, refined, notes = self.run_session([0.5], broken)
        self.assertEqual(len(segs), 1)
        self.assertEqual(refined, [])
        self.assertIn("로컬 글을 그대로", notes[0])


class RefinementStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patch = patch.object(po_note, "NOTES_DIR", Path(self.temp.name) / "po_notes")
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_refinement_replaces_lines_or_merges_them(self):
        note_id = po_note.create()["id"]
        for i in range(3):
            po_note.append_segment(note_id, {"id": i, "start": i * 5, "end": i * 5 + 4, "text": f"초안{i}", "conf": 0.5, "src": "local"})
        self.assertEqual(po_note.next_segment_id(note_id), 3)
        items = po_note.apply_refinement(note_id, [0, 1], ["고친 0", ""])
        self.assertEqual([(x["id"], x["text"], x["src"]) for x in items], [(0, "고친 0", "server"), (2, "초안2", "local")])
        items = po_note.apply_refinement(note_id, [0, 2], "합친 글")
        self.assertEqual([(x["start"], x["end"], x["text"]) for x in items], [(0, 14, "합친 글")])


class LevelTests(unittest.TestCase):
    def test_quiet_audio_is_raised_but_loud_audio_is_left_alone(self):
        try:
            import numpy as np
        except ImportError:
            self.skipTest("numpy 없음")
        quiet = (np.sin(np.arange(16000) / 5) * 0.01).astype(np.float32)
        raised = stt.level(quiet)
        self.assertAlmostEqual(float(np.sqrt(np.mean(raised ** 2))), stt.LEVEL_TARGET_RMS, places=3)
        loud = (np.sin(np.arange(16000) / 5) * 0.5).astype(np.float32)
        self.assertIs(stt.level(loud).dtype, np.dtype(np.float32))
        self.assertTrue(np.array_equal(stt.level(loud), loud))
        hiss = np.full(1600, 1e-5, dtype=np.float32)  # 거의 무음은 최대 배율까지만
        self.assertAlmostEqual(float(stt.level(hiss)[0]), 1e-5 * stt.LEVEL_MAX_GAIN, places=7)
        spiky = np.zeros(16000, dtype=np.float32)
        spiky[0] = 0.9  # RMS는 작지만 큰 값 하나: 키워도 ±1을 넘지 않는다
        self.assertLessEqual(float(np.abs(stt.level(spiky)).max()), 1.0)
        self.assertEqual(len(stt.level(np.zeros(0, dtype=np.float32))), 0)


class ResamplerTests(unittest.TestCase):
    def test_48k_blocks_become_16k(self):
        try:
            import numpy as np
        except ImportError:
            self.skipTest("numpy 없음")
        r = stt._Resampler(48000)
        out = np.concatenate([r(np.ones(4800, dtype=np.float32)) for _ in range(10)])
        self.assertLessEqual(abs(len(out) - 16000), 2)


if __name__ == "__main__":
    unittest.main()
