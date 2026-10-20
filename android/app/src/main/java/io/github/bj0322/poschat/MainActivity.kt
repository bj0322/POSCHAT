package io.github.bj0322.poschat

import android.Manifest
import android.content.ActivityNotFoundException
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.provider.DocumentsContract
import android.provider.Settings
import android.util.Log
import android.webkit.ConsoleMessage
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.MimeTypeMap
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.ActivityResultLauncher
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.FileProvider
import androidx.webkit.WebViewAssetLoader
import androidx.webkit.WebViewClientCompat
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONObject
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors

/**
 * 데스크톱 앱의 web/ 화면을 WebView로 띄우고, 화면의 window.pywebview.api 호출을 Python(android_main.py)으로 넘긴다.
 * pywebview가 하던 일(JS ↔ Python, 폴더 고르기, 파일 열기)을 이 클래스가 대신한다.
 */
class MainActivity : ComponentActivity() {
    internal lateinit var webView: WebView  // 계측 테스트에서 화면 상태를 확인한다
    private val executor = Executors.newCachedThreadPool()
    private val pythonReady = CountDownLatch(1)
    @Volatile private var bridge: PyObject? = null
    @Volatile private var startError: String? = null

    private lateinit var pickFolder: ActivityResultLauncher<Uri?>
    @Volatile private var folderLatch: CountDownLatch? = null
    @Volatile private var pickedFolder: String? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        pickFolder = registerForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
            pickedFolder = uri?.let { treeUriToPath(it) }
            if (uri != null && pickedFolder == null) {
                toast("이 위치는 작업 폴더로 쓸 수 없습니다. 내부 저장소나 SD 카드의 폴더를 고르세요.")
            }
            folderLatch?.countDown()
        }

        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG)
        webView = WebView(this)
        setContentView(webView)
        webView.settings.javaScriptEnabled = true
        webView.settings.domStorageEnabled = true
        webView.addJavascriptInterface(JsHost(), "PoschatHost")
        // 화면의 오류·콘솔 출력을 logcat(태그 PoschatWeb)에 남긴다
        webView.webChromeClient = object : WebChromeClient() {
            override fun onConsoleMessage(message: ConsoleMessage): Boolean {
                Log.i("PoschatWeb", "${message.message()} (${message.sourceId()}:${message.lineNumber()})")
                return true
            }
        }

        // https://appassets.androidplatform.net/assets/... 로 앱 안의 파일을 웹 페이지처럼 연다(file:// 제약 없음).
        val assets = WebViewAssetLoader.Builder()
            .addPathHandler("/assets/", WebViewAssetLoader.AssetsPathHandler(this))
            .build()
        webView.webViewClient = object : WebViewClientCompat() {
            override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? =
                assets.shouldInterceptRequest(request.url)

            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                if (request.url.host == WebViewAssetLoader.DEFAULT_DOMAIN) return false
                // 답변 속 링크는 브라우저로 연다
                try {
                    startActivity(Intent(Intent.ACTION_VIEW, request.url))
                } catch (e: ActivityNotFoundException) {
                    toast("링크를 열 앱이 없습니다.")
                }
                return true
            }

            override fun onPageFinished(view: WebView, url: String) {
                view.evaluateJavascript(BRIDGE_SHIM, null)
            }
        }

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                // 열린 창이나 사이드바가 있으면 화면이 닫고(true), 없으면 앱을 뒤로 보낸다.
                webView.evaluateJavascript("window.__androidBack ? window.__androidBack() : false") { handled ->
                    if (handled != "true") {
                        isEnabled = false
                        onBackPressedDispatcher.onBackPressed()
                        isEnabled = true
                    }
                }
            }
        })

        executor.execute { startPython() }
        webView.loadUrl("https://${WebViewAssetLoader.DEFAULT_DOMAIN}/assets/web/index.html")
    }

    override fun onDestroy() {
        if (isFinishing) bridge?.let { b -> executor.execute { runCatching { b.callAttr("shutdown") } } }
        webView.destroy()
        super.onDestroy()
    }

    private fun startPython() {
        try {
            if (!Python.isStarted()) Python.start(AndroidPlatform(this))
            val resDir = File(filesDir, "res")
            copyAssetDir("skills", File(resDir, "skills"))
            val module = Python.getInstance().getModule("android_main")
            module.callAttr("start", Host(), filesDir.absolutePath, resDir.absolutePath)
            bridge = module
        } catch (e: Throwable) {
            startError = e.toString()
            Log.e("Poschat", "Python을 시작하지 못했습니다", e)
        } finally {
            pythonReady.countDown()
        }
    }

    /** 앱에 묶인 assets/<name> 폴더를 실제 파일로 복사한다(Python이 경로로 읽는다). */
    private fun copyAssetDir(name: String, target: File) {
        val children = assets.list(name) ?: return
        if (children.isEmpty()) {
            target.parentFile?.mkdirs()
            assets.open(name).use { input -> target.outputStream().use { input.copyTo(it) } }
            return
        }
        target.mkdirs()
        for (child in children) copyAssetDir("$name/$child", File(target, child))
    }

    /** 화면(JS) → Python. 결과는 window.__pyResolve(id, 성공 여부, JSON)으로 돌려준다. */
    inner class JsHost {
        @JavascriptInterface
        fun call(id: Int, method: String, argsJson: String) {
            executor.execute {
                val reply = try {
                    pythonReady.await()
                    val module = bridge ?: throw IllegalStateException("Python을 시작하지 못했습니다: $startError")
                    "true, " + module.callAttr("call", method, argsJson).toString()
                } catch (e: Throwable) {
                    "false, " + JSONObject.quote(e.message ?: e.toString())
                }
                Host().evalJs("window.__pyResolve($id, $reply)")
            }
        }
    }

    /** Python(android_main.py) → 안드로이드. Python 스레드에서 불린다. */
    inner class Host {
        fun evalJs(script: String) {
            runOnUiThread { webView.evaluateJavascript(script, null) }
        }

        /** 작업 폴더 고르기. 고른 폴더의 실제 경로, 취소하거나 쓸 수 없으면 null. */
        fun pickFolder(): String? {
            if (!hasStorageAccess()) {
                runOnUiThread { requestStorageAccess() }
                return null
            }
            val latch = CountDownLatch(1)
            pickedFolder = null
            folderLatch = latch
            runOnUiThread { pickFolder.launch(null) }
            latch.await()
            return pickedFolder
        }

        /** 데스크톱의 os.startfile: 파일은 알맞은 앱으로 열고, 폴더는 경로를 알려 준다. */
        fun openPath(path: String) {
            runOnUiThread {
                val file = File(path)
                when {
                    file.isDirectory -> toast("폴더 위치: $path")
                    !file.exists() -> toast("파일이 없습니다: $path")
                    else -> openFile(file)
                }
            }
        }
    }

    private fun openFile(file: File) {
        val ext = file.extension.lowercase()
        val mime = when (ext) {
            "md", "txt", "json", "py", "log" -> "text/plain"
            else -> MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext) ?: "*/*"
        }
        val uri = FileProvider.getUriForFile(this, "$packageName.files", file)
        val intent = Intent(Intent.ACTION_VIEW).setDataAndType(uri, mime)
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
        try {
            startActivity(Intent.createChooser(intent, file.name))
        } catch (e: ActivityNotFoundException) {
            toast("이 파일을 열 앱이 없습니다: ${file.name}")
        }
    }

    private fun hasStorageAccess(): Boolean =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            Environment.isExternalStorageManager()
        } else {
            checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE) == PackageManager.PERMISSION_GRANTED
        }

    private fun requestStorageAccess() {
        toast("작업 폴더의 파일을 읽고 고치려면 '모든 파일 접근' 권한이 필요합니다. 허용한 뒤 다시 폴더를 고르세요.")
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            try {
                startActivity(Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION, Uri.parse("package:$packageName")))
            } catch (e: ActivityNotFoundException) {
                startActivity(Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION))
            }
        } else {
            requestPermissions(
                arrayOf(Manifest.permission.READ_EXTERNAL_STORAGE, Manifest.permission.WRITE_EXTERNAL_STORAGE), 1,
            )
        }
    }

    /** 문서 선택기가 돌려준 폴더(content://…/tree/primary:Documents/x)를 실제 경로로 바꾼다. */
    private fun treeUriToPath(uri: Uri): String? {
        if (uri.authority != "com.android.externalstorage.documents") return null
        val docId = DocumentsContract.getTreeDocumentId(uri)
        val volume = docId.substringBefore(":")
        val relative = docId.substringAfter(":", "")
        val base = if (volume.equals("primary", ignoreCase = true)) {
            Environment.getExternalStorageDirectory().path
        } else {
            "/storage/$volume"
        }
        return if (relative.isEmpty()) base else "$base/$relative"
    }

    private fun toast(text: String) {
        runOnUiThread { Toast.makeText(this, text, Toast.LENGTH_LONG).show() }
    }

    companion object {
        /** 화면에 pywebview와 같은 window.pywebview.api를 만들어 준다. app.js는 pywebviewready 이벤트로 시작한다. */
        private val BRIDGE_SHIM = """
            (function () {
              if (window.pywebview) return;
              var seq = 0, pending = {};
              window.__pyResolve = function (id, ok, payload) {
                var p = pending[id];
                delete pending[id];
                if (p) ok ? p.resolve(payload) : p.reject(new Error(payload));
              };
              var api = new Proxy({}, {
                get: function (_, name) {
                  return function () {
                    var args = Array.prototype.slice.call(arguments);
                    return new Promise(function (resolve, reject) {
                      var id = ++seq;
                      pending[id] = { resolve: resolve, reject: reject };
                      PoschatHost.call(id, String(name), JSON.stringify(args));
                    });
                  };
                },
              });
              window.pywebview = { api: api, platform: "android" };
              window.addEventListener("unhandledrejection", function (e) {
                window.__lastError = String(e.reason && (e.reason.stack || e.reason.message) || e.reason);
                console.error("unhandled: " + window.__lastError);
              });
              window.__androidBack = function () {
                if (document.querySelector(".modal-backdrop")) {
                  document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
                  return true;
                }
                var app = document.getElementById("app");
                if (app && !app.classList.contains("collapsed") && window.matchMedia("(max-width: 720px)").matches) {
                  setCollapsed(true);
                  return true;
                }
                return false;
              };
              window.dispatchEvent(new Event("pywebviewready"));
            })();
        """.trimIndent()
    }
}
