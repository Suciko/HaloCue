package com.halocue.android

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class VivoImportNavigatorTest {
    private val task = AaImportTask(
        project = "NavigatorProbe",
        displayName = "NavigatorProbe.aap",
        sourceUri = "content://media/external/downloads/123",
        state = AaImportState.IMPORTING,
        phase = AaImportPhase.OPEN_SOURCE_STORAGE,
        message = "正在导入原版 AA…",
        updatedAt = 1L,
    )
    private val navigator = VivoImportNavigator()

    @Test
    fun waits_without_acting_when_another_app_is_in_front() {
        val action = navigator.nextAction(
            snapshot(
                packageName = "com.android.settings",
                phase = AaImportPhase.SELECT_SOURCE,
                longClickableTexts = setOf(task.displayName),
            ),
        )

        assertTrue(action is VivoImportAction.Wait)
    }

    @Test
    fun waits_without_acting_until_the_user_has_started_an_import() {
        val action = navigator.nextAction(
            snapshot(
                phase = AaImportPhase.OPEN_SOURCE_STORAGE,
                state = AaImportState.NEEDS_ACCESSIBILITY,
                clickableTexts = setOf("手机存储"),
            ),
        )

        assertTrue(action is VivoImportAction.Wait)
    }

    @Test
    fun long_presses_only_the_pending_source_file() {
        val action = navigator.nextAction(
            snapshot(
                phase = AaImportPhase.SELECT_SOURCE,
                longClickableTexts = setOf(task.displayName, "unrelated.aap"),
            ),
        )

        assertEquals(
            VivoImportAction.LongClickText(task.displayName, AaImportPhase.CHOOSE_COPY),
            action,
        )
    }

    @Test
    fun chooses_copy_without_advancing_on_unrelated_actions() {
        val action = navigator.nextAction(
            snapshot(
                phase = AaImportPhase.CHOOSE_COPY,
                clickableTexts = setOf("删除", "移动", "复制"),
            ),
        )

        assertEquals(
            VivoImportAction.ClickText("复制", AaImportPhase.OPEN_DESTINATION_STORAGE),
            action,
        )
    }

    @Test
    fun follows_the_exact_source_and_AA_destination_directory_order() {
        val expected = listOf(
            AaImportPhase.OPEN_SOURCE_STORAGE to "手机存储",
            AaImportPhase.OPEN_DOWNLOAD to "Download",
            AaImportPhase.OPEN_HALOCUE to "HaloCue",
            AaImportPhase.OPEN_DESTINATION_STORAGE to "手机存储",
            AaImportPhase.OPEN_ANDROID to "Android",
            AaImportPhase.OPEN_ANDROID_DATA to "data",
            AaImportPhase.OPEN_AA_PACKAGE to "com.foxxlight.AzureArchive",
            AaImportPhase.OPEN_AA_FILES to "files",
            AaImportPhase.OPEN_AA_DATA to "data",
            AaImportPhase.OPEN_PROJECTS to "projects",
            AaImportPhase.PASTE to "粘贴",
        )

        expected.forEach { (phase, label) ->
            val action = navigator.nextAction(snapshot(phase = phase, clickableTexts = setOf(label)))
            assertTrue("$phase should click $label but was $action", action is VivoImportAction.ClickText)
            assertEquals(label, (action as VivoImportAction.ClickText).text)
        }
    }

    @Test
    fun fails_instead_of_confirming_a_same_name_or_replace_dialog() {
        val action = navigator.nextAction(
            snapshot(
                phase = AaImportPhase.PASTE,
                visibleTexts = setOf("目标位置已存在同名文件", "替换", "取消"),
                clickableTexts = setOf("替换", "取消"),
            ),
        )

        assertEquals(VivoImportAction.Fail("AA 中已有同名工程，请修改工程名"), action)
    }

    @Test
    fun completes_only_after_the_file_manager_reports_copy_success() {
        val action = navigator.nextAction(
            snapshot(
                phase = AaImportPhase.VERIFY_COPY,
                visibleTexts = setOf("复制成功"),
            ),
        )

        assertEquals(VivoImportAction.Complete("已导入原版 AA"), action)
    }

    private fun snapshot(
        packageName: String = "com.android.filemanager",
        phase: AaImportPhase,
        state: AaImportState = AaImportState.IMPORTING,
        visibleTexts: Set<String> = emptySet(),
        clickableTexts: Set<String> = emptySet(),
        longClickableTexts: Set<String> = emptySet(),
    ) = VivoUiSnapshot(
        packageName = packageName,
        visibleTexts = visibleTexts,
        clickableTexts = clickableTexts,
        longClickableTexts = longClickableTexts,
        task = task.copy(phase = phase, state = state),
    )
}
