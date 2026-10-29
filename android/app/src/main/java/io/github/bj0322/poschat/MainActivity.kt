// SPDX-FileCopyrightText: 2026 Beomjoon Kim
// SPDX-License-Identifier: AGPL-3.0-only
package io.github.bj0322.poschat

import android.Manifest
import android.content.ActivityNotFoundException
import android.content.Intent
import android.content.pm.PackageManager
import android.content.res.Configuration
import android.graphics.Bitmap
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
import android.webkit.PermissionRequest
import android.webkit.WebViewClient
import android.widget.LinearLayout
import android.webkit.ValueCallback
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
import java.util.concurrent.TimeUnit

/**
 * 데스크톱 앱의 web/ 화면을 WebView로 띄우고, 화면의 window.pywebview.api 호출을 Python(android_main.py)으로 넘긴다.
 * pywebview가 하던 일(JS ↔ Python, 폴더 고르기, 파일 열기)을 이 클래스가 대신한다.
 */
class MainActivity : ComponentActivity() {
    internal lateinit var webView: WebView  // 계측 테스트에서 화면 상태를 확인한다
    // 1.13 브라우저: 앱 화면과 나란히 두는 웹페이지 뷰. POSCHAT API(JavascriptInterface)를 주지 않는다.
    internal var browserView: WebView? = null
    private lateinit var root: LinearLayout
    @Volatile private var browserRatio = 0.55
    private val executor = Executors.newCachedThreadPool()
    private val pythonReady = CountDownLatch(1)
    @Volatile private var bridge: PyObject? = null
    @Volatile private var startError: String? = null

    private lateinit var pickFolder: ActivityResultLauncher<Uri?>
    @Volatile private var folderLatch: CountDownLatch? = null
    @Volatile private var pickedFolder: String? = null

    // 화면의 <input type="file">(채팅창 첨부 버튼)
    private lateinit var pickFiles: ActivityResultLauncher<Intent>
    // PO노트 녹음: 마이크(필수)·알림(녹음 중 표시, 선택) 권한
    private lateinit var micPermission: ActivityResultLauncher<Array<String>>
    @Volatile private var micLatch: CountDownLatch? = null
    private lateinit var installPermission: ActivityResultLauncher<Intent>
    private var pendingApkUri: Uri? = null
    private var filesCallback: ValueCallback<Array<Uri>>? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        installPermission = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) {
            val uri = pendingApkUri
            pendingApkUri = null
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O || packageManager.canRequestPackageInstalls()) {
                uri?.let { launchApkInstaller(it) }
            } else toast("설치 권한이 허용되지 않았습니다. 설정에서 허용한 뒤 다시 업데이트를 선택하세요.")
        }
        pickFolder = registerForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
            pickedFolder = uri?.let { treeUriToPath(it) }
            if (uri != null && pickedFolder == null) {
                toast("이 위치는 작업 폴더로 쓸 수 없습니다. 내부 저장소나 SD 카드의 폴더를 고르세요.")
            }
            folderLatch?.countDown()
        }
        micPermission = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
            micLatch?.countDown()
        }
        pickFiles = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
            val data = result.data
            val uris = when {
                result.resultCode != RESULT_OK || data == null -> null
                data.clipData != null -> Array(data.clipData!!.itemCount) { data.clipData!!.getItemAt(it).uri }
                data.data != null -> arrayOf(data.data!!)
                else -> null
            }
            filesCallback?.onReceiveValue(uris)
            filesCallback = null
        }

        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG)
        webView = WebView(this)
        root = LinearLayout(this)
        root.addView(webView, LinearLayout.LayoutParams(0, 0, 1f))
        setContentView(root)
        layoutPanes()
        webView.settings.javaScriptEnabled = true
        webView.settings.domStorageEnabled = true
        webView.addJavascriptInterface(JsHost(), "PoschatHost")
        // 화면의 오류·콘솔 출력을 logcat(태그 PoschatWeb)에 남긴다
        webView.webChromeClient = object : WebChromeClient() {
            override fun onConsoleMessage(message: ConsoleMessage): Boolean {
                Log.i("PoschatWeb", "${message.message()} (${message.sourceId()}:${message.lineNumber()})")
                return true
            }

            override fun onShowFileChooser(
                view: WebView, callback: ValueCallback<Array<Uri>>, params: FileChooserParams,
            ): Boolean {
                filesCallback?.onReceiveValue(null)  // 앞의 선택 창이 답 없이 남아 있으면 끝낸다
                filesCallback = callback
                val intent = Intent(Intent.ACTION_GET_CONTENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*")
                    .putExtra(Intent.EXTRA_ALLOW_MULTIPLE, params.mode == FileChooserParams.MODE_OPEN_MULTIPLE)
                return try {
                    pickFiles.launch(Intent.createChooser(intent, "첨부할 파일"))
                    true
                } catch (e: ActivityNotFoundException) {
                    filesCallback = null
                    toast("파일을 고를 앱이 없습니다.")
                    false
                }
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
                // 브라우저가 열려 있고 뒤로 갈 페이지가 있으면 웹페이지부터 뒤로
                browserView?.let { b ->
                    if (b.visibility == android.view.View.VISIBLE && b.canGoBack()) {
                        b.goBack()
                        return
                    }
                }
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

    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        layoutPanes()
    }

    /** 세로 화면은 위(웹페이지)·아래(앱), 가로 화면은 왼쪽(앱)·오른쪽(웹페이지). */
    private fun layoutPanes() {
        val landscape = resources.configuration.orientation == Configuration.ORIENTATION_LANDSCAPE
        root.orientation = if (landscape) LinearLayout.HORIZONTAL else LinearLayout.VERTICAL
        val b = browserView
        val shown = b != null && b.visibility == android.view.View.VISIBLE
        val appWeight = if (shown) (1 - browserRatio).toFloat() else 1f
        webView.layoutParams = LinearLayout.LayoutParams(0, 0, appWeight).also {
            if (landscape) it.height = LinearLayout.LayoutParams.MATCH_PARENT else it.width = LinearLayout.LayoutParams.MATCH_PARENT
        }
        if (b != null) {
            root.removeView(b)
            root.addView(b, if (landscape) 1 else 0, LinearLayout.LayoutParams(0, 0, browserRatio.toFloat()).also {
                if (landscape) it.height = LinearLayout.LayoutParams.MATCH_PARENT else it.width = LinearLayout.LayoutParams.MATCH_PARENT
            })
        }
        root.requestLayout()
    }

    /** 브라우저 이벤트를 Python(browser.Browser)으로 넘긴다. Python이 앱 화면에 알린다. */
    private fun browserEvent(fields: Map<String, Any?>) {
        val json = JSONObject(fields).toString()
        executor.execute {
            runCatching { pythonReady.await(); bridge?.callAttr("browser_event", json) }
        }
    }

    private fun browserReport(view: WebView, loading: Boolean) {
        browserEvent(mapOf("url" to (view.url ?: ""), "title" to (view.title ?: ""), "loading" to loading,
            "can_back" to view.canGoBack(), "can_forward" to view.canGoForward()))
    }

    private fun allowedUrl(uri: Uri?): Boolean =
        uri != null && (uri.scheme == "http" || uri.scheme == "https") && !uri.host.isNullOrEmpty() &&
            uri.host != WebViewAssetLoader.DEFAULT_DOMAIN

    private fun ensureBrowser(): WebView {
        browserView?.let { return it }
        val b = WebView(this)
        b.settings.javaScriptEnabled = true
        b.settings.domStorageEnabled = true
        b.settings.allowFileAccess = false
        b.settings.allowContentAccess = false
        b.settings.setSupportMultipleWindows(false)  // target=_blank도 같은 뷰에서 연다
        b.settings.builtInZoomControls = true
        b.settings.displayZoomControls = false
        // addJavascriptInterface를 하지 않는다: 웹페이지가 POSCHAT을 부를 길이 없다
        b.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                if (allowedUrl(request.url)) return false
                browserEvent(mapOf("kind" to "blocked", "url" to request.url.toString(), "reason" to "http·https 주소만 열 수 있습니다."))
                return true
            }

            override fun onPageStarted(view: WebView, url: String, favicon: Bitmap?) {
                browserReport(view, true)
            }

            override fun onPageFinished(view: WebView, url: String) {
                browserReport(view, false)
            }
        }
        b.webChromeClient = object : WebChromeClient() {
            override fun onPermissionRequest(request: PermissionRequest) {
                request.deny()  // 카메라·마이크 등
            }

            override fun onReceivedTitle(view: WebView, title: String?) {
                browserReport(view, view.progress < 100)
            }
        }
        b.setDownloadListener { url, _, _, _, _ ->
            browserEvent(mapOf("kind" to "blocked", "url" to url, "reason" to "다운로드는 기본 브라우저에서 하세요(외부 브라우저로 열기)."))
        }
        b.visibility = android.view.View.GONE
        browserView = b
        layoutPanes()
        return b
    }

    override fun onDestroy() {
        if (isFinishing) bridge?.let { b -> executor.execute { runCatching { b.callAttr("shutdown") } } }
        webView.destroy()
        browserView?.destroy()
        super.onDestroy()
    }

    private fun startPython() {
        try {
            if (!Python.isStarted()) Python.start(AndroidPlatform(this))
            val resDir = File(filesDir, "res")
            copyAssetDir("skills", File(resDir, "skills"))
            // 설정 > 라이선스가 읽는 라이선스 전문·제3자 고지
            for (name in listOf("LICENSE", "THIRD_PARTY_NOTICES.md", "licenses")) copyAssetDir(name, File(resDir, name))
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

        /** PO노트 녹음 시작: 마이크 권한을 받고 녹음 서비스를 연다. 실패하면 이유, 성공하면 null. */
        fun micStart(): String? {
            if (!hasMic()) {
                val latch = CountDownLatch(1)
                micLatch = latch
                val wanted = mutableListOf(Manifest.permission.RECORD_AUDIO)
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) wanted += Manifest.permission.POST_NOTIFICATIONS
                runOnUiThread { micPermission.launch(wanted.toTypedArray()) }
                latch.await(2, TimeUnit.MINUTES)  // 답 없이 화면이 닫히면 녹음 시작만 실패한다
                if (!hasMic()) return "마이크 권한이 없어 녹음할 수 없습니다. 설정 > 앱 > POSCHAT > 권한에서 마이크를 허용하세요."
            }
            return RecordingService.start(this@MainActivity)
        }

        fun micStop() {
            RecordingService.stop(this@MainActivity)
        }

        // ---- 1.13 브라우저(android_main.AndroidBrowser가 부른다) ----

        fun browserShow(ratio: Double) {
            browserRatio = ratio.coerceIn(0.25, 0.8)
            runOnUiThread {
                ensureBrowser().visibility = android.view.View.VISIBLE
                layoutPanes()
            }
        }

        fun browserHide() {
            runOnUiThread {
                browserView?.visibility = android.view.View.GONE
                layoutPanes()
            }
        }

        fun browserOpen(url: String) {
            runOnUiThread { if (allowedUrl(Uri.parse(url))) ensureBrowser().loadUrl(url) }
        }

        fun browserNav(action: String) {
            runOnUiThread {
                browserView?.let {
                    when (action) {
                        "back" -> it.goBack()
                        "forward" -> it.goForward()
                        "reload" -> it.reload()
                        "stop" -> it.stopLoading()
                    }
                }
            }
        }

        fun browserRatio(ratio: Double) {
            browserRatio = ratio.coerceIn(0.25, 0.8)
            runOnUiThread { layoutPanes() }
        }

        /** 웹페이지에서 script를 실행해 결과(JSON 문자열)를 돌려준다. Python 스레드에서 불린다. */
        fun browserRead(script: String): String {
            val latch = CountDownLatch(1)
            var result = ""
            runOnUiThread {
                val b = browserView
                if (b == null) latch.countDown() else b.evaluateJavascript(script) { value ->
                    result = value ?: ""
                    latch.countDown()
                }
            }
            latch.await(15, TimeUnit.SECONDS)
            return result
        }

        fun browserClose() {
            runOnUiThread {
                browserView?.let { root.removeView(it); it.destroy() }
                browserView = null
                layoutPanes()
            }
        }

        /** 데스크톱의 os.startfile: https 주소(OAuth 로그인 등)는 브라우저로, 파일은 알맞은 앱으로 열고, 폴더는 경로를 알려 준다. */
        fun openPath(path: String) {
            runOnUiThread {
                if (path.startsWith("https://") || path.startsWith("http://127.0.0.1:")) {
                    try {
                        startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(path)))
                    } catch (e: ActivityNotFoundException) {
                        toast("브라우저를 열 수 없습니다: $path")
                    }
                    return@runOnUiThread
                }
                val file = File(path)
                when {
                    file.isDirectory -> toast("폴더 위치: $path")
                    !file.exists() -> toast("파일이 없습니다: $path")
                    file.extension.equals("apk", ignoreCase = true) -> installApk(file)
                    else -> openFile(file)
                }
            }
        }
    }

    private fun installApk(file: File) {
        val uri = FileProvider.getUriForFile(this, "$packageName.files", file)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && !packageManager.canRequestPackageInstalls()) {
            pendingApkUri = uri
            installPermission.launch(
                Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:$packageName")),
            )
        } else launchApkInstaller(uri)
    }

    private fun launchApkInstaller(uri: Uri) {
        try {
            startActivity(
                Intent(Intent.ACTION_INSTALL_PACKAGE).setDataAndType(uri, "application/vnd.android.package-archive")
                    .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION),
            )
        } catch (e: ActivityNotFoundException) {
            toast("이 기기에서 Android 설치 프로그램을 열 수 없습니다.")
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

    private fun hasMic(): Boolean =
        checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED

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
