package com.halocue.android

data class VivoUiSnapshot(
    val packageName: String,
    val visibleTexts: Set<String>,
    val clickableTexts: Set<String>,
    val longClickableTexts: Set<String>,
    val task: AaImportTask,
)

sealed interface VivoImportAction {
    data class ClickText(
        val text: String,
        val nextPhase: AaImportPhase,
    ) : VivoImportAction

    data class LongClickText(
        val text: String,
        val nextPhase: AaImportPhase,
    ) : VivoImportAction

    data class Wait(val reason: String) : VivoImportAction
    data class Complete(val message: String) : VivoImportAction
    data class Fail(val message: String) : VivoImportAction
}

class VivoImportNavigator {
    fun nextAction(snapshot: VivoUiSnapshot): VivoImportAction {
        if (snapshot.task.state != AaImportState.IMPORTING) {
            return VivoImportAction.Wait("等待用户开始导入")
        }
        if (snapshot.packageName != FILE_MANAGER_PACKAGE) {
            return VivoImportAction.Wait("等待 vivo 文件管理器")
        }
        if (snapshot.visibleTexts.any { text -> CONFLICT_MARKERS.any(text::contains) }) {
            return VivoImportAction.Fail("AA 中已有同名工程，请修改工程名")
        }

        return when (snapshot.task.phase) {
            AaImportPhase.SELECT_SOURCE -> {
                if (snapshot.task.displayName in snapshot.longClickableTexts) {
                    VivoImportAction.LongClickText(
                        snapshot.task.displayName,
                        AaImportPhase.CHOOSE_COPY,
                    )
                } else {
                    VivoImportAction.Wait("等待生成文件出现")
                }
            }
            AaImportPhase.CHOOSE_COPY -> clickWhenVisible(
                snapshot,
                label = "复制",
                nextPhase = AaImportPhase.OPEN_DESTINATION_STORAGE,
            )
            AaImportPhase.VERIFY_COPY -> {
                if (snapshot.visibleTexts.any { it.contains("复制成功") }) {
                    VivoImportAction.Complete("已导入原版 AA")
                } else {
                    VivoImportAction.Wait("等待文件复制完成")
                }
            }
            else -> {
                val step = DIRECTORY_STEPS[snapshot.task.phase]
                    ?: return VivoImportAction.Wait("等待可识别的文件管理器界面")
                clickWhenVisible(snapshot, step.first, step.second)
            }
        }
    }

    private fun clickWhenVisible(
        snapshot: VivoUiSnapshot,
        label: String,
        nextPhase: AaImportPhase,
    ): VivoImportAction =
        if (label in snapshot.clickableTexts) {
            VivoImportAction.ClickText(label, nextPhase)
        } else {
            VivoImportAction.Wait("等待“$label”")
        }

    companion object {
        const val FILE_MANAGER_PACKAGE = "com.android.filemanager"
        private val CONFLICT_MARKERS = setOf("同名", "替换", "覆盖")
        private val DIRECTORY_STEPS = mapOf(
            AaImportPhase.OPEN_SOURCE_STORAGE to ("手机存储" to AaImportPhase.OPEN_DOWNLOAD),
            AaImportPhase.OPEN_DOWNLOAD to ("Download" to AaImportPhase.OPEN_HALOCUE),
            AaImportPhase.OPEN_HALOCUE to ("HaloCue" to AaImportPhase.SELECT_SOURCE),
            AaImportPhase.OPEN_DESTINATION_STORAGE to ("手机存储" to AaImportPhase.OPEN_ANDROID),
            AaImportPhase.OPEN_ANDROID to ("Android" to AaImportPhase.OPEN_ANDROID_DATA),
            AaImportPhase.OPEN_ANDROID_DATA to ("data" to AaImportPhase.OPEN_AA_PACKAGE),
            AaImportPhase.OPEN_AA_PACKAGE to ("com.foxxlight.AzureArchive" to AaImportPhase.OPEN_AA_FILES),
            AaImportPhase.OPEN_AA_FILES to ("files" to AaImportPhase.OPEN_AA_DATA),
            AaImportPhase.OPEN_AA_DATA to ("data" to AaImportPhase.OPEN_PROJECTS),
            AaImportPhase.OPEN_PROJECTS to ("projects" to AaImportPhase.PASTE),
            AaImportPhase.PASTE to ("粘贴" to AaImportPhase.VERIFY_COPY),
        )
    }
}
