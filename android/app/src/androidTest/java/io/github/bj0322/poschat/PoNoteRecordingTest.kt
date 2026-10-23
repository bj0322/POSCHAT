// SPDX-FileCopyrightText: 2026 Beomjoon Kim
// SPDX-License-Identifier: AGPL-3.0-only
package io.github.bj0322.poschat

import android.Manifest
import android.os.Build
import android.util.Log
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.rule.GrantPermissionRule
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.FixMethodOrder
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.runners.MethodSorters
import java.io.File

/**
 * PO노트 녹음을 휴대폰(에뮬레이터)에서 확인한다(CI가 돌린다).
 * 1) 앱에 넣은 sherpa-onnx C 라이브러리로 시험 음성을 인식해 정확도·속도를 잰다(po_bench, 결과는 logcat PoschatBench).
 * 2) 녹음 서비스가 마이크를 열어 Python으로 소리를 넘기는지, 3) 화면이 부르는 po_start/po_stop이 끝까지 도는지.
 * 모델(약 76MB)을 처음 한 번 내려받으므로 인터넷이 필요하다.
 */
@RunWith(AndroidJUnit4::class)
@FixMethodOrder(MethodSorters.NAME_ASCENDING)
class PoNoteRecordingTest {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext

    @get:Rule
    val permissions: GrantPermissionRule = if (Build.VERSION.SDK_INT >= 33) {
        GrantPermissionRule.grant(Manifest.permission.RECORD_AUDIO, Manifest.permission.POST_NOTIFICATIONS)
    } else GrantPermissionRule.grant(Manifest.permission.RECORD_AUDIO)

    private fun python(): Python {
        // 화면(MainActivity)도 Python을 시작하므로 먼저 시작했으면 그대로 쓴다
        if (!Python.isStarted()) runCatching { Python.start(AndroidPlatform(context)) }
        return Python.getInstance()
    }

    private fun module(): PyObject = python().getModule("android_main")

    @Test
    fun a_localRecognitionAccuracyAndSpeed() {
        val files = File(context.filesDir, "bench").absolutePath
        val json = python().getModule("po_bench")
            .callAttr("main", files, files, File(context.cacheDir, "test_wavs").absolutePath).toString()
        Log.i("PoschatBench", json)
        val report = JSONObject(json)
        assertEquals("sherpa_capi", report.getString("backend"))
        assertTrue(report.getJSONArray("available").getBoolean(0))
        val wavs = report.getJSONObject("files")
        for (name in wavs.keys()) {
            val item = wavs.getJSONObject(name)
            assertTrue("$name: $item", item.getDouble("cer") < 0.05)
        }
        val quiet = report.getJSONObject("quiet")
        assertTrue("작은 소리도 받아 적어야 한다: $quiet", quiet.getDouble("cer") < 0.1)
        val pipe = report.getJSONObject("pipeline")
        assertEquals(pipe.toString(), 4, pipe.getJSONArray("segments").length())
        assertTrue(pipe.toString(), pipe.getDouble("cer") < 0.05)
        assertEquals(0, pipe.getJSONArray("errors").length())
        assertTrue("실시간보다 느리면 녹음이 밀린다: $pipe", pipe.getDouble("rtf") < 1.0)
    }

    @Test
    fun b_recordingServiceDeliversMicrophoneAudio() {
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            var activity: MainActivity? = null
            scenario.onActivity { activity = it }
            val host = activity!!.Host()
            val before = JSONObject(module().callAttr("mic_stats").toString()).getInt("blocks")
            assertNull(host.micStart())
            Thread.sleep(2500)
            host.micStop()
            val blocks = JSONObject(module().callAttr("mic_stats").toString()).getInt("blocks") - before
            Log.i("PoschatBench", "mic blocks in 2.5s: $blocks")
            assertTrue("녹음 서비스가 0.1초 블록을 넘겨야 한다: $blocks", blocks >= 15)
        }
    }

    @Test
    fun c_poNoteStartAndStopThroughTheBridge() {
        ActivityScenario.launch(MainActivity::class.java).use {
            val main = module()
            fun call(method: String, vararg args: Any): String =
                main.callAttr("call", method, JSONArray(args).toString()).toString()

            // 화면이 Python과 연결될 때까지(android_main.start) 기다린다
            val deadline = System.currentTimeMillis() + 60_000
            while (System.currentTimeMillis() < deadline) {
                if (runCatching { call("po_state") }.isSuccess) break
                Thread.sleep(500)
            }
            call("po_save_settings", JSONObject(mapOf("engine" to "local", "model" to "ko")))
            val state = JSONObject(call("po_state"))
            assertTrue(state.toString(), state.getBoolean("available"))
            val noteId = JSONObject(call("po_create", "recording test")).getString("id")
            val started = JSONObject(call("po_start", noteId))
            assertTrue(started.toString(), started.getBoolean("ok"))
            Thread.sleep(3000)
            val recording = JSONObject(call("po_state")).getJSONObject("recording")
            assertTrue("받은 소리로 녹음 시간이 늘어야 한다: $recording", recording.getDouble("elapsed") > 1.5)
            call("po_stop")
            val stopDeadline = System.currentTimeMillis() + 30_000
            while (System.currentTimeMillis() < stopDeadline && !JSONObject(call("po_state")).isNull("recording")) {
                Thread.sleep(200)
            }
            assertTrue("녹음이 끝나야 한다", JSONObject(call("po_state")).isNull("recording"))
            assertTrue(JSONObject(module().callAttr("mic_stats").toString()).getBoolean("active").not())
            call("po_delete", noteId)
        }
    }
}
