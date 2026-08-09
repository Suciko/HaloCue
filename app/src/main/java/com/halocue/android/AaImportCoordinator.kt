package com.halocue.android

import android.accessibilityservice.AccessibilityServiceInfo
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.provider.Settings
import android.view.accessibility.AccessibilityManager

enum class AaImportNextAction {
    NONE,
    OPEN_ACCESSIBILITY_SETTINGS,
    START_VIVO_FILE_MANAGER,
}

data class AaImportOutcome(
    val task: AaImportTask,
    val nextAction: AaImportNextAction,
)

class AaImportCoordinator(
    context: Context,
    private val taskStore: AaImportTaskStore = AaImportTaskStore(context),
) {
    private val applicationContext = context.applicationContext

    fun prepare(exported: PublicAapExportResult, project: String): AaImportOutcome {
        require(project.isNotBlank()) { "工程名不能为空" }

        val initial = AaImportTask(
            project = project,
            displayName = exported.displayName,
            sourceUri = exported.uri.toString(),
            state = AaImportState.READY,
            message = "已准备导入",
            updatedAt = System.currentTimeMillis(),
        )
        val outcome = when {
            applicationContext.packageManager.getLaunchIntentForPackage(AA_PACKAGE) == null -> {
                AaImportOutcome(
                    initial.copy(
                        state = AaImportState.FAILED,
                        message = "尚未安装原版 AA",
                    ),
                    AaImportNextAction.NONE,
                )
            }
            !isImportServiceEnabled() -> {
                AaImportOutcome(
                    initial.copy(
                        state = AaImportState.NEEDS_ACCESSIBILITY,
                        message = "首次使用需要开启自动导入",
                    ),
                    AaImportNextAction.OPEN_ACCESSIBILITY_SETTINGS,
                )
            }
            else -> {
                AaImportOutcome(
                    initial.copy(
                        state = AaImportState.IMPORTING,
                        message = "正在导入原版 AA…",
                    ),
                    AaImportNextAction.START_VIVO_FILE_MANAGER,
                )
            }
        }
        taskStore.save(outcome.task)
        return outcome
    }

    fun accessibilitySettingsIntent(): Intent =
        Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)

    fun vivoFileManagerLaunchIntent(): Intent =
        applicationContext.packageManager.getLaunchIntentForPackage(VIVO_FILE_MANAGER_PACKAGE)
            ?.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            ?: throw ActivityNotFoundException("未找到 vivo 文件管理器")

    private fun isImportServiceEnabled(): Boolean {
        val manager = applicationContext.getSystemService(AccessibilityManager::class.java)
        val expectedName = "${applicationContext.packageName}.VivoAaImportAccessibilityService"
        return manager
            .getEnabledAccessibilityServiceList(AccessibilityServiceInfo.FEEDBACK_ALL_MASK)
            .any { info ->
                info.resolveInfo.serviceInfo.packageName == applicationContext.packageName &&
                    info.resolveInfo.serviceInfo.name == expectedName
            }
    }

    companion object {
        private const val AA_PACKAGE = "com.foxxlight.AzureArchive"
        private const val VIVO_FILE_MANAGER_PACKAGE = "com.android.filemanager"
    }
}
