package com.halocue.android

import android.accessibilityservice.AccessibilityService
import android.content.Intent
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo

class VivoAaImportAccessibilityService : AccessibilityService() {
    private lateinit var taskStore: AaImportTaskStore
    private val navigator = VivoImportNavigator()

    override fun onServiceConnected() {
        super.onServiceConnected()
        taskStore = AaImportTaskStore(this)
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (!::taskStore.isInitialized) {
            taskStore = AaImportTaskStore(this)
        }
        val task = taskStore.load() ?: return
        if (task.state != AaImportState.IMPORTING) return

        val now = System.currentTimeMillis()
        if (now - task.updatedAt > PHASE_TIMEOUT_MILLIS) {
            taskStore.save(
                task.copy(
                    state = AaImportState.FAILED,
                    message = "自动导入超时，请继续导入",
                    updatedAt = now,
                ),
            )
            return
        }

        val root = rootInActiveWindow ?: return
        val snapshot = buildSnapshot(root, task, event?.packageName?.toString())
        when (val action = navigator.nextAction(snapshot)) {
            is VivoImportAction.ClickText -> {
                if (performTextAction(root, action.text, AccessibilityNodeInfo.ACTION_CLICK)) {
                    advance(task, action.nextPhase, now)
                }
            }
            is VivoImportAction.LongClickText -> {
                if (performTextAction(root, action.text, AccessibilityNodeInfo.ACTION_LONG_CLICK)) {
                    advance(task, action.nextPhase, now)
                }
            }
            is VivoImportAction.Complete -> complete(task, action.message, now)
            is VivoImportAction.Fail -> taskStore.save(
                task.copy(
                    state = AaImportState.FAILED,
                    message = action.message,
                    updatedAt = now,
                ),
            )
            is VivoImportAction.Wait -> Unit
        }
    }

    override fun onInterrupt() = Unit

    private fun advance(task: AaImportTask, nextPhase: AaImportPhase, now: Long) {
        taskStore.save(
            task.copy(
                phase = nextPhase,
                updatedAt = now,
            ),
        )
    }

    private fun complete(task: AaImportTask, message: String, now: Long) {
        taskStore.save(
            task.copy(
                state = AaImportState.IMPORTED,
                message = message,
                updatedAt = now,
            ),
        )
        packageManager.getLaunchIntentForPackage(AA_PACKAGE)?.let { intent ->
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            startActivity(intent)
        }
    }

    private fun buildSnapshot(
        root: AccessibilityNodeInfo,
        task: AaImportTask,
        eventPackageName: String?,
    ): VivoUiSnapshot {
        val visibleTexts = linkedSetOf<String>()
        val clickableTexts = linkedSetOf<String>()
        val longClickableTexts = linkedSetOf<String>()
        visit(root) { node ->
            val label = nodeLabel(node) ?: return@visit
            visibleTexts += label
            if (actionableAncestor(node, longClick = false) != null) clickableTexts += label
            if (actionableAncestor(node, longClick = true) != null) longClickableTexts += label
        }
        return VivoUiSnapshot(
            packageName = root.packageName?.toString() ?: eventPackageName.orEmpty(),
            visibleTexts = visibleTexts,
            clickableTexts = clickableTexts,
            longClickableTexts = longClickableTexts,
            task = task,
        )
    }

    private fun performTextAction(
        root: AccessibilityNodeInfo,
        label: String,
        action: Int,
    ): Boolean {
        var target: AccessibilityNodeInfo? = null
        visit(root) { node ->
            if (target == null && nodeLabel(node) == label) {
                target = actionableAncestor(
                    node,
                    longClick = action == AccessibilityNodeInfo.ACTION_LONG_CLICK,
                )
            }
        }
        return target?.performAction(action) == true
    }

    private fun actionableAncestor(
        node: AccessibilityNodeInfo,
        longClick: Boolean,
    ): AccessibilityNodeInfo? {
        var current: AccessibilityNodeInfo? = node
        while (current != null) {
            if (if (longClick) current.isLongClickable else current.isClickable) return current
            current = current.parent
        }
        return null
    }

    private fun nodeLabel(node: AccessibilityNodeInfo): String? =
        (node.text ?: node.contentDescription)
            ?.toString()
            ?.trim()
            ?.takeIf(String::isNotEmpty)

    private fun visit(node: AccessibilityNodeInfo, block: (AccessibilityNodeInfo) -> Unit) {
        block(node)
        for (index in 0 until node.childCount) {
            node.getChild(index)?.let { child -> visit(child, block) }
        }
    }

    companion object {
        private const val AA_PACKAGE = "com.foxxlight.AzureArchive"
        private const val PHASE_TIMEOUT_MILLIS = 20_000L
    }
}
