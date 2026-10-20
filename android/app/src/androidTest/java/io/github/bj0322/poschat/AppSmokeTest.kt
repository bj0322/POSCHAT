package io.github.bj0322.poschat

import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** 에뮬레이터에서 설치된 앱이 제대로 묶였고 화면과 Python이 연결되는지 확인한다(CI가 돌린다). */
@RunWith(AndroidJUnit4::class)
class AppSmokeTest {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext

    @Test
    fun pythonBundleWorks() {
        if (!Python.isStarted()) Python.start(AndroidPlatform(context))
        val resDir = File(context.cacheDir, "test-res")
        copyAssets("skills", File(resDir, "skills"))
        val json = Python.getInstance().getModule("android_main")
            .callAttr("selftest", File(context.cacheDir, "test-files").absolutePath, resDir.absolutePath)
            .toString()
        println("selftest: $json")
        val report = JSONObject(json)
        assertEquals(BuildConfig.VERSION_NAME, report.getString("version"))
        assertEquals("OK", report.getString("documents"))
        val mcp = report.getJSONObject("mcp")
        assertEquals(3, mcp.getInt("word"))
        assertEquals(3, mcp.getInt("powerpoint"))
        assertEquals(2, mcp.getInt("excel"))
        assertEquals(5, mcp.getInt("paper"))
        assertEquals(6, mcp.getInt("notion"))
        assertEquals(7, mcp.getInt("hyperframes"))
        assertTrue(report.getString("video_create").startsWith("OK"))
        assertEquals("OK", report.getString("word_create"))
        assertTrue(report.getString("word_read").contains("제목"))
        assertTrue(report.getJSONArray("skills").toString().contains("summarize"))
    }

    @Test
    fun screenLoadsAndTalksToPython() {
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            // app.js의 init()이 Python Bridge.get_state()를 받아 S.version을 채우면 화면과 Python이 연결된 것이다.
            val probe = """
                (function () {
                  if (typeof S === "undefined" || !S.version) {
                    return "WAIT " + JSON.stringify({ href: location.href, title: document.title,
                      bridge: !!window.pywebview, host: typeof PoschatHost, S: typeof S,
                      error: window.__lastError || null });
                  }
                  var md = renderMarkdown("\\(x^2\\)");
                  return JSON.stringify({ version: S.version, katex: !!md.querySelector(".katex"),
                                          narrow: isNarrow(), collapsed: document.getElementById("app").classList.contains("collapsed") });
                })()
            """.trimIndent()
            var result = ""
            val deadline = System.currentTimeMillis() + 60_000
            while (System.currentTimeMillis() < deadline) {
                val latch = CountDownLatch(1)
                scenario.onActivity { activity ->
                    activity.webView.evaluateJavascript(probe) { value ->
                        result = value
                        latch.countDown()
                    }
                }
                latch.await(10, TimeUnit.SECONDS)
                if (result.length > 4 && !result.startsWith("\"WAIT")) break
                Thread.sleep(1000)
            }
            println("screen: $result")
            assertTrue("화면이 Python과 연결되지 않았습니다: $result", result.length > 4 && !result.startsWith("\"WAIT"))
            // evaluateJavascript는 문자열 결과를 JSON 문자열로 한 번 더 감싸서 준다
            val state = JSONObject(JSONObject("{\"v\":$result}").getString("v"))
            assertEquals(BuildConfig.VERSION_NAME, state.getString("version"))
            assertTrue("KaTeX 수식 렌더링", state.getBoolean("katex"))
            assertTrue("휴대폰 화면에서는 사이드바가 닫힌 채로 시작", !state.getBoolean("narrow") || state.getBoolean("collapsed"))
        }
    }

    private fun copyAssets(name: String, target: File) {
        val children = context.assets.list(name) ?: return
        if (children.isEmpty()) {
            target.parentFile?.mkdirs()
            context.assets.open(name).use { input -> target.outputStream().use { input.copyTo(it) } }
            return
        }
        target.mkdirs()
        for (child in children) copyAssets("$name/$child", File(target, child))
    }
}
