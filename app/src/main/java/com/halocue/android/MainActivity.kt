package com.halocue.android

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.provider.DocumentsContract
import android.provider.OpenableColumns
import android.view.View
import android.view.ViewGroup
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.annotation.VisibleForTesting
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import java.io.File
import java.util.ArrayDeque
import java.util.concurrent.Executors
import org.json.JSONArray
import org.json.JSONObject

internal fun isInternalWebUiUrl(uri: Uri, activePort: Int?): Boolean {
    if (uri.toString() == "file:///android_asset/index.html") return true
    return activePort != null &&
        uri.scheme == "http" &&
        uri.host == "127.0.0.1" &&
        uri.port == activePort
}

internal fun canPublishDocumentResult(
    isFinishing: Boolean,
    isDestroyed: Boolean,
    pageReady: Boolean,
    deliveryDestroyed: Boolean,
): Boolean = !isFinishing && !isDestroyed && pageReady && !deliveryDestroyed

internal fun createInsetWebViewContainer(context: Context, content: View): FrameLayout =
    FrameLayout(context).apply {
        addView(
            content,
            FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT,
            ),
        )
        ViewCompat.setOnApplyWindowInsetsListener(this) { view, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            view.setPadding(0, bars.top, 0, bars.bottom)
            insets
        }
    }

@Suppress("SetJavaScriptEnabled")
internal fun createSecureWebView(context: Context): WebView = WebView(context).apply {
    settings.javaScriptEnabled = true
    settings.domStorageEnabled = true
    settings.allowContentAccess = false
    settings.allowFileAccess = false
    settings.allowFileAccessFromFileURLs = false
    settings.allowUniversalAccessFromFileURLs = false
    webChromeClient = WebChromeClient()
}

class MainActivity : ComponentActivity() {
    private lateinit var webView: WebView
    private lateinit var webRuntime: LocalWebRuntime
    private val runtimeExecutor = Executors.newSingleThreadExecutor()
    private val compilerExecutor = Executors.newSingleThreadExecutor()
    private val documentExecutor = Executors.newSingleThreadExecutor()
    private val documentPicker = AndroidDocumentPicker()
    private lateinit var incomingFileStore: IncomingFileStore
    private val documentResultLock = Any()
    private var pendingDocumentResult: JSONObject? = null
    private var documentDeliveryDestroyed = false
    private var pageReady = false

    private val documentLauncher = registerForActivityResult(
        ActivityResultContracts.OpenDocument(),
    ) { uri -> handleDocumentResult(uri) }

    private val documentTreeLauncher = registerForActivityResult(
        ActivityResultContracts.OpenDocumentTree(),
    ) { uri -> handleDocumentResult(uri) }

    @Volatile
    private var activeSession: LocalWebSession? = null

    @Volatile
    private var lastExport: PublicAapExportResult? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        restoreDocumentRequest(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        AndroidRuntimeRegistry.initialize(applicationContext)
        LegacyImportStateCleaner.clear(this)
        incomingFileStore = IncomingFileStore(applicationContext.filesDir)

        webRuntime = LocalWebRuntime(this)
        webView = createWebView()
        setContentView(createInsetWebViewContainer(this, webView))
        startLocalWebUi()
    }

    private fun restoreDocumentRequest(savedInstanceState: Bundle?) {
        val requestId = savedInstanceState?.getString(STATE_DOCUMENT_REQUEST_ID).orEmpty()
        val purpose = savedInstanceState?.getString(STATE_DOCUMENT_PURPOSE).orEmpty()
        val assetKind = savedInstanceState?.getString(STATE_DOCUMENT_ASSET_KIND).orEmpty()
        val suffixes = savedInstanceState
            ?.getStringArrayList(STATE_DOCUMENT_SUFFIXES)
            ?.toSet()
            .orEmpty()
        if (requestId.isNotBlank() && purpose.isNotBlank() && suffixes.isNotEmpty()) {
            runCatching {
                DocumentPickRequest.fromBridge(requestId, purpose, assetKind, suffixes)
            }.getOrNull()?.let(documentPicker::restore)
        }
        savedInstanceState?.getString(STATE_DOCUMENT_RESULT)?.let { serialized ->
            runCatching { JSONObject(serialized) }.getOrNull()?.let { result ->
                synchronized(documentResultLock) { pendingDocumentResult = result }
            }
        }
    }

    private fun startLocalWebUi() {
        runtimeExecutor.execute {
            try {
                val session = webRuntime.start()
                activeSession = session
                runOnUiThread {
                    if (!isFinishing && !isDestroyed) webView.loadUrl(session.url)
                }
            } catch (error: Exception) {
                val fallbackHtml = runCatching {
                    assets.open(FALLBACK_ASSET_NAME).bufferedReader().use { it.readText() }
                }.getOrElse {
                    "<h1>HaloCue failed to start</h1>"
                }
                runOnUiThread {
                    if (!isFinishing && !isDestroyed) {
                        webView.loadDataWithBaseURL(
                            FALLBACK_ASSET_URL,
                            fallbackHtml,
                            "text/html",
                            Charsets.UTF_8.name(),
                            null,
                        )
                        Toast.makeText(
                            this,
                            "本地服务启动失败：${error.javaClass.simpleName}",
                            Toast.LENGTH_LONG,
                        ).show()
                    }
                }
            }
        }
    }

    private fun createWebView(): WebView = createSecureWebView(this).apply {
        id = R.id.main_webview
        setBackgroundColor(Color.rgb(244, 247, 251))
        addJavascriptInterface(AndroidBridge(), NATIVE_BRIDGE_NAME)

        webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(
                view: WebView,
                request: WebResourceRequest,
            ): Boolean {
                if (isInternalUrl(request.url)) return false
                if (request.url.scheme == "https") return openExternalUrl(request.url)
                return true
            }

            override fun onPageFinished(view: WebView, url: String) {
                pageReady = true
                publishPendingDocumentResult()
            }
        }

    }

    private fun isInternalUrl(uri: Uri): Boolean {
        return isInternalWebUiUrl(uri, activeSession?.port)
    }

    private fun openExternalUrl(uri: Uri): Boolean = try {
        startActivity(Intent(Intent.ACTION_VIEW, uri))
        true
    } catch (_: ActivityNotFoundException) {
        Toast.makeText(this, "没有可打开此链接的应用", Toast.LENGTH_SHORT).show()
        true
    }

    private fun openAzureArchive() {
        val launchIntent = packageManager.getLaunchIntentForPackage(AA_PACKAGE)
        if (launchIntent == null) {
            Toast.makeText(this, "尚未安装原版 AA", Toast.LENGTH_SHORT).show()
            return
        }
        startActivity(launchIntent)
    }

    private fun generateAndExport(project: String, text: String) {
        compilerExecutor.execute {
            lastExport = null
            publishExportPayload(
                JSONObject()
                    .put("state", "GENERATING")
                    .put("message", "正在本机生成...")
                    .put("shareAvailable", false),
            )
            try {
                require(project.isNotBlank()) { "工程名不能为空" }
                require(text.isNotBlank()) { "剧本文本不能为空" }
                val compiled = AndroidCompilerBridge(this).compileText(text = text, project = project)
                val exported = AapPublicExporter(this).export(
                    source = File(compiled.aapFile),
                    project = compiled.project,
                )
                lastExport = exported
                publishExportPayload(
                    JSONObject()
                        .put("state", "EXPORTED")
                        .put("message", "已生成，尚未导入原版 AA")
                        .put("displayName", exported.displayName)
                        .put("relativePath", exported.relativePath)
                        .put("shareAvailable", true),
                )
            } catch (error: Exception) {
                lastExport = null
                publishExportPayload(
                    JSONObject()
                        .put("state", "FAILED")
                        .put("message", error.message ?: "生成失败")
                        .put("shareAvailable", false),
                )
            }
        }
    }

    private fun shareLastExport() {
        val exported = lastExport
        if (exported == null) {
            Toast.makeText(this, "尚未生成工程文件", Toast.LENGTH_SHORT).show()
            return
        }
        try {
            startActivity(
                Intent.createChooser(
                    AapShareIntentFactory.create(exported.uri, exported.displayName),
                    "分享工程文件",
                ),
            )
        } catch (_: ActivityNotFoundException) {
            Toast.makeText(this, "没有可分享此文件的应用", Toast.LENGTH_SHORT).show()
        }
    }

    private fun shareExport(shareId: String) {
        val intent = AndroidRuntimeRegistry.platformServices().shareIntent(shareId)
        if (intent == null) {
            Toast.makeText(this, "分享记录已失效，请重新编译", Toast.LENGTH_SHORT).show()
            return
        }
        try {
            startActivity(Intent.createChooser(intent, "分享工程文件"))
        } catch (_: ActivityNotFoundException) {
            Toast.makeText(this, "没有可分享此文件的应用", Toast.LENGTH_SHORT).show()
        }
    }

    private fun pickDocument(
        requestId: String,
        purpose: String,
        assetKind: String,
        suffixesJson: String,
    ) {
        val suffixes = runCatching {
            val values = JSONArray(suffixesJson)
            buildSet {
                for (index in 0 until values.length()) {
                    val suffix = values.optString(index).trim().lowercase()
                    if (suffix.matches(Regex("\\.[a-z0-9]{1,12}"))) add(suffix)
                }
            }
        }.getOrElse { emptySet() }
        val request = runCatching {
            DocumentPickRequest.fromBridge(requestId, purpose, assetKind, suffixes)
        }.getOrNull()
        if (request == null) {
            publishDocumentPicked(
                JSONObject()
                    .put("requestId", requestId)
                    .put("ok", false)
                    .put("code", "invalid_request")
                    .put("message", "Invalid document picker request"),
            )
            return
        }
        if (!documentPicker.begin(request)) {
            publishDocumentPicked(
                JSONObject()
                    .put("requestId", requestId)
                    .put("ok", false)
                    .put("code", "picker_busy")
                    .put("message", "Another document picker is already open"),
            )
            return
        }
        try {
            if (request.usesDirectoryTree) {
                documentTreeLauncher.launch(null)
            } else {
                documentLauncher.launch(mimeTypesFor(request))
            }
        } catch (_: ActivityNotFoundException) {
            documentPicker.consume()
            publishDocumentPicked(
                JSONObject()
                    .put("requestId", requestId)
                    .put("ok", false)
                    .put("code", "picker_unavailable")
                    .put("message", "No system document picker is available"),
            )
        }
    }

    private fun mimeTypesFor(request: DocumentPickRequest): Array<String> = when (request.purpose) {
        DocumentPickPurpose.STORY -> arrayOf(
            "text/plain",
            "text/markdown",
            "application/octet-stream",
        )
        DocumentPickPurpose.ASSET_FILE -> when (request.assetKind) {
            "background" -> arrayOf("image/png", "image/jpeg")
            "sound" -> arrayOf("audio/wav", "audio/ogg", "audio/mpeg", "application/ogg")
            else -> arrayOf("application/octet-stream")
        }
        DocumentPickPurpose.ASSET_TREE -> emptyArray()
    }

    private fun handleDocumentResult(uri: Uri?) {
        val request = documentPicker.consume() ?: return
        if (uri == null) {
            publishDocumentPicked(
                JSONObject()
                    .put("requestId", request.requestId)
                    .put("purpose", request.purpose.wireValue)
                    .put("assetKind", request.assetKind)
                    .put("ok", false)
                    .put("code", "cancelled"),
            )
            return
        }
        documentExecutor.execute {
            val payload = try {
                if (request.usesDirectoryTree) {
                    val incoming = stageDocumentTree(uri, request)
                    JSONObject()
                        .put("requestId", request.requestId)
                        .put("purpose", request.purpose.wireValue)
                        .put("assetKind", request.assetKind)
                        .put("ok", true)
                        .put("token", incoming.token)
                        .put("name", incoming.name)
                        .put("size", incoming.size)
                        .put("fileCount", incoming.fileCount)
                        .put("selectionType", "tree")
                } else {
                    val displayName = queryDisplayName(uri) ?: defaultDocumentName(request)
                    val incoming = contentResolver.openInputStream(uri)?.use { input ->
                        incomingFileStore.stage(
                            displayName = displayName,
                            input = input,
                            allowedSuffixes = request.allowedSuffixes,
                            maxBytes = maxDocumentBytes(request),
                        )
                    } ?: error("Unable to open selected document")
                    JSONObject()
                        .put("requestId", request.requestId)
                        .put("purpose", request.purpose.wireValue)
                        .put("assetKind", request.assetKind)
                        .put("ok", true)
                        .put("token", incoming.token)
                        .put("name", incoming.name)
                        .put("size", incoming.size)
                        .put("selectionType", "file")
                }
            } catch (error: Exception) {
                JSONObject()
                    .put("requestId", request.requestId)
                    .put("purpose", request.purpose.wireValue)
                    .put("assetKind", request.assetKind)
                    .put("ok", false)
                    .put(
                        "code",
                        (error as? IncomingFileStoreException)?.code ?: "document_copy_failed",
                    )
                    .put("message", error.message ?: "Unable to copy selected document")
            }
            publishDocumentPicked(payload)
        }
    }

    private fun stageDocumentTree(
        treeUri: Uri,
        request: DocumentPickRequest,
    ): IncomingTree {
        val rootDocumentId = DocumentsContract.getTreeDocumentId(treeUri)
        val rootDocumentUri = DocumentsContract.buildDocumentUriUsingTree(treeUri, rootDocumentId)
        val displayName = queryDisplayName(rootDocumentUri) ?: "assets"
        val entries = collectDocumentTreeEntries(
            treeUri,
            rootDocumentId,
            request.allowedSuffixes,
        )
        return incomingFileStore.stageTree(
            displayName = displayName,
            entries = entries,
            allowedSuffixes = request.allowedSuffixes,
            maxFiles = MAX_TREE_FILES,
            maxFileBytes = MAX_TREE_FILE_BYTES,
            maxTotalBytes = MAX_TREE_BYTES,
        )
    }

    private fun collectDocumentTreeEntries(
        treeUri: Uri,
        rootDocumentId: String,
        allowedSuffixes: Set<String>,
    ): List<IncomingTreeEntry> {
        data class PendingDirectory(
            val documentId: String,
            val relativePath: String,
            val depth: Int,
        )

        val pending = ArrayDeque<PendingDirectory>()
        val visitedDirectories = mutableSetOf<String>()
        val entries = mutableListOf<IncomingTreeEntry>()
        pending.add(PendingDirectory(rootDocumentId, "", 0))
        while (pending.isNotEmpty()) {
            val directory = pending.removeFirst()
            if (!visitedDirectories.add(directory.documentId)) {
                throw IncomingFileStoreException(
                    "unsafe_tree_path",
                    "Directory provider returned a repeated directory",
                )
            }
            if (visitedDirectories.size > MAX_TREE_DIRECTORIES) {
                throw IncomingFileStoreException(
                    "too_many_files",
                    "Directory contains too many folders",
                )
            }
            val childrenUri = DocumentsContract.buildChildDocumentsUriUsingTree(
                treeUri,
                directory.documentId,
            )
            contentResolver.query(
                childrenUri,
                arrayOf(
                    DocumentsContract.Document.COLUMN_DOCUMENT_ID,
                    DocumentsContract.Document.COLUMN_DISPLAY_NAME,
                    DocumentsContract.Document.COLUMN_MIME_TYPE,
                ),
                null,
                null,
                null,
            )?.use { cursor ->
                val idColumn = cursor.getColumnIndexOrThrow(
                    DocumentsContract.Document.COLUMN_DOCUMENT_ID,
                )
                val nameColumn = cursor.getColumnIndexOrThrow(
                    DocumentsContract.Document.COLUMN_DISPLAY_NAME,
                )
                val mimeColumn = cursor.getColumnIndexOrThrow(
                    DocumentsContract.Document.COLUMN_MIME_TYPE,
                )
                while (cursor.moveToNext()) {
                    val documentId = cursor.getString(idColumn)
                    val name = cursor.getString(nameColumn).orEmpty()
                    val relativePath = if (directory.relativePath.isEmpty()) {
                        name
                    } else {
                        "${directory.relativePath}/$name"
                    }
                    if (cursor.getString(mimeColumn) == DocumentsContract.Document.MIME_TYPE_DIR) {
                        if (directory.depth >= MAX_TREE_DEPTH) {
                            throw IncomingFileStoreException(
                                "unsafe_tree_path",
                                "Directory nesting is too deep",
                            )
                        }
                        pending.add(
                            PendingDirectory(
                                documentId = documentId,
                                relativePath = relativePath,
                                depth = directory.depth + 1,
                            ),
                        )
                    } else {
                        if (!hasAllowedDocumentSuffix(relativePath, allowedSuffixes)) continue
                        if (entries.size >= MAX_TREE_FILES) {
                            throw IncomingFileStoreException(
                                "too_many_files",
                                "Directory contains too many files",
                            )
                        }
                        val documentUri = DocumentsContract.buildDocumentUriUsingTree(
                            treeUri,
                            documentId,
                        )
                        entries.add(
                            IncomingTreeEntry(relativePath) {
                                contentResolver.openInputStream(documentUri)
                                    ?: error("Unable to open a selected directory file")
                            },
                        )
                    }
                }
            } ?: throw IllegalStateException("Unable to read selected directory")
        }
        return entries
    }

    private fun defaultDocumentName(request: DocumentPickRequest): String = when {
        request.purpose == DocumentPickPurpose.STORY -> "story.txt"
        request.assetKind == "background" -> "background.png"
        request.assetKind == "sound" -> "sound.ogg"
        else -> "document.bin"
    }

    private fun maxDocumentBytes(request: DocumentPickRequest): Long =
        if (request.purpose == DocumentPickPurpose.STORY) MAX_STORY_BYTES else MAX_ASSET_FILE_BYTES

    private fun queryDisplayName(uri: Uri): String? {
        return contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)
            ?.use { cursor ->
                if (!cursor.moveToFirst()) return@use null
                val index = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (index < 0) null else cursor.getString(index)
            }
    }

    private fun publishDocumentPicked(payload: JSONObject) {
        val discardedToken = synchronized(documentResultLock) {
            if (documentDeliveryDestroyed) payload.optString("token") else {
                pendingDocumentResult = payload
                ""
            }
        }
        if (discardedToken.isNotEmpty()) {
            incomingFileStore.discard(discardedToken)
            return
        }
        publishPendingDocumentResult()
    }

    private fun publishPendingDocumentResult() {
        runOnUiThread {
            val deliveryDestroyed = synchronized(documentResultLock) {
                documentDeliveryDestroyed
            }
            if (
                ::webView.isInitialized && canPublishDocumentResult(
                    isFinishing,
                    isDestroyed,
                    pageReady,
                    deliveryDestroyed,
                )
            ) {
                val payload = synchronized(documentResultLock) {
                    if (documentDeliveryDestroyed) return@synchronized null
                    pendingDocumentResult?.let { JSONObject(it.toString()) }
                } ?: return@runOnUiThread
                webView.evaluateJavascript(
                    "window.HaloCueAndroid && window.HaloCueAndroid.documentPicked($payload);",
                    null,
                )
            }
        }
    }

    private fun acknowledgeDocumentResult(requestId: String, claimed: Boolean) {
        val discardedToken = synchronized(documentResultLock) {
            val current = pendingDocumentResult
            if (current?.optString("requestId") != requestId) return
            pendingDocumentResult = null
            if (claimed) "" else current.optString("token")
        }
        if (discardedToken.isNotEmpty()) incomingFileStore.discard(discardedToken)
    }

    private fun publishExportPayload(payload: JSONObject) {
        runOnUiThread {
            if (!isFinishing && ::webView.isInitialized && pageReady) {
                webView.evaluateJavascript(
                    "window.HaloCueApp && window.HaloCueApp.exportUpdated($payload);",
                    null,
                )
            }
        }
    }

    private inner class AndroidBridge {
        @JavascriptInterface
        fun isAzureArchiveInstalled(): Boolean =
            packageManager.getLaunchIntentForPackage(AA_PACKAGE) != null

        @JavascriptInterface
        fun openAzureArchive() {
            runOnUiThread { this@MainActivity.openAzureArchive() }
        }

        @JavascriptInterface
        fun generateAndExport(project: String, text: String) {
            this@MainActivity.generateAndExport(project, text)
        }

        @JavascriptInterface
        fun shareLastExport() {
            runOnUiThread { this@MainActivity.shareLastExport() }
        }

        @JavascriptInterface
        fun shareExport(shareId: String) {
            runOnUiThread { this@MainActivity.shareExport(shareId) }
        }

        @JavascriptInterface
        fun pickDocument(requestId: String, purpose: String, suffixesJson: String) {
            runOnUiThread {
                this@MainActivity.pickDocument(requestId, purpose, "", suffixesJson)
            }
        }

        @JavascriptInterface
        fun pickAsset(requestId: String, purpose: String, assetKind: String, suffixesJson: String) {
            runOnUiThread {
                this@MainActivity.pickDocument(requestId, purpose, assetKind, suffixesJson)
            }
        }

        @JavascriptInterface
        fun ackDocumentResult(requestId: String, claimed: Boolean) {
            this@MainActivity.acknowledgeDocumentResult(requestId, claimed)
        }
    }

    @VisibleForTesting
    fun webViewForTest(): WebView = webView

    @VisibleForTesting
    fun isInternalUrlForTest(uri: Uri): Boolean = isInternalUrl(uri)

    @Deprecated("Android system back compatibility")
    override fun onBackPressed() {
        if (webView.canGoBack()) webView.goBack() else super.onBackPressed()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        documentPicker.current()?.let { request ->
            outState.putString(STATE_DOCUMENT_REQUEST_ID, request.requestId)
            outState.putString(STATE_DOCUMENT_PURPOSE, request.purpose.wireValue)
            outState.putString(STATE_DOCUMENT_ASSET_KIND, request.assetKind)
            outState.putStringArrayList(
                STATE_DOCUMENT_SUFFIXES,
                ArrayList(request.allowedSuffixes),
            )
        }
        synchronized(documentResultLock) {
            pendingDocumentResult?.let { result ->
                outState.putString(STATE_DOCUMENT_RESULT, result.toString())
            }
        }
        super.onSaveInstanceState(outState)
    }

    override fun onDestroy() {
        val discardedToken = synchronized(documentResultLock) {
            documentDeliveryDestroyed = true
            if (isChangingConfigurations) "" else pendingDocumentResult?.optString("token").orEmpty()
        }
        if (discardedToken.isNotEmpty()) incomingFileStore.discard(discardedToken)
        runtimeExecutor.shutdownNow()
        compilerExecutor.shutdownNow()
        documentExecutor.shutdownNow()
        if (::webView.isInitialized) {
            webView.removeJavascriptInterface(NATIVE_BRIDGE_NAME)
            webView.destroy()
        }
        if (::webRuntime.isInitialized) webRuntime.stop()
        super.onDestroy()
    }

    companion object {
        private const val AA_PACKAGE = "com.foxxlight.AzureArchive"
        private const val FALLBACK_ASSET_NAME = "index.html"
        private const val FALLBACK_ASSET_URL = "file:///android_asset/index.html"
        private const val NATIVE_BRIDGE_NAME = "HaloCueNative"
        private const val MAX_STORY_BYTES = 10L * 1024 * 1024
        private const val MAX_ASSET_FILE_BYTES = 128L * 1024 * 1024
        private const val MAX_TREE_FILES = 1024
        private const val MAX_TREE_DIRECTORIES = 4096
        private const val MAX_TREE_DEPTH = 16
        private const val MAX_TREE_FILE_BYTES = 64L * 1024 * 1024
        private const val MAX_TREE_BYTES = 512L * 1024 * 1024
        private const val STATE_DOCUMENT_REQUEST_ID = "document_request_id"
        private const val STATE_DOCUMENT_PURPOSE = "document_purpose"
        private const val STATE_DOCUMENT_ASSET_KIND = "document_asset_kind"
        private const val STATE_DOCUMENT_SUFFIXES = "document_suffixes"
        private const val STATE_DOCUMENT_RESULT = "document_result"
    }
}
