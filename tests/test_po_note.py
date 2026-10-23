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
