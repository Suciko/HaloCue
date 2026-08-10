package com.halocue.android

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import java.io.ByteArrayInputStream
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.assertThrows
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class IncomingFileStoreTest {
    @Test
    fun stages_a_sanitized_private_copy_with_opaque_token() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val root = context.cacheDir.resolve("incoming-test-${System.nanoTime()}")
        try {
            val store = IncomingFileStore(root)
            val result = store.stage(
                displayName = "../../story.md",
                input = ByteArrayInputStream("# story".toByteArray()),
                allowedSuffixes = setOf(".txt", ".md"),
                maxBytes = 10L * 1024 * 1024,
            )

            assertEquals("story.md", result.name)
            assertEquals(7L, result.size)
            assertTrue(result.token.matches(Regex("[a-f0-9]{32}")))
            assertEquals(
                "# story",
                root.resolve("incoming/${result.token}.bin").readText(),
            )
            assertFalse(root.resolve("story.md").exists())
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun rejects_unsupported_and_oversized_documents_without_leaving_payloads() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val root = context.cacheDir.resolve("incoming-test-${System.nanoTime()}")
        try {
            val store = IncomingFileStore(root)
            val unsupported = runCatching {
                store.stage(
                    "story.exe",
                    ByteArrayInputStream(byteArrayOf(1)),
                    setOf(".txt", ".md"),
                    10,
                )
            }.exceptionOrNull() as IncomingFileStoreException
            assertEquals("unsupported_type", unsupported.code)

            val oversized = runCatching {
                store.stage(
                    "story.txt",
                    ByteArrayInputStream(ByteArray(11)),
                    setOf(".txt", ".md"),
                    10,
                )
            }.exceptionOrNull() as IncomingFileStoreException
            assertEquals("file_too_large", oversized.code)
            assertTrue(root.resolve("incoming").listFiles().isNullOrEmpty())
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun picker_consumes_each_request_once() {
        val picker = AndroidDocumentPicker()
        val request = DocumentPickRequest.fromBridge(
            requestId = "request-1",
            purpose = "story",
            assetKind = "",
            allowedSuffixes = setOf(".txt", ".md"),
        )

        assertTrue(picker.begin(request))
        assertFalse(picker.begin(request.copy(requestId = "request-2")))
        assertEquals(request, picker.consume())
        assertEquals(null, picker.consume())
    }

    @Test
    fun picker_request_can_be_restored_after_activity_recreation() {
        val original = AndroidDocumentPicker()
        val request = DocumentPickRequest.fromBridge(
            requestId = "request-rotate",
            purpose = "asset_tree",
            assetKind = "character",
            allowedSuffixes = setOf(".skel", ".atlas", ".png"),
        )
        assertTrue(original.begin(request))

        val restored = AndroidDocumentPicker()
        assertTrue(restored.restore(original.current()!!))

        assertEquals(request, restored.consume())
    }

    @Test
    fun picker_request_validates_native_asset_modes() {
        val background = DocumentPickRequest.fromBridge(
            requestId = "background",
            purpose = "asset_file",
            assetKind = "background",
            allowedSuffixes = setOf(".png", ".jpg"),
        )
        val character = DocumentPickRequest.fromBridge(
            requestId = "character",
            purpose = "asset_tree",
            assetKind = "character",
            allowedSuffixes = setOf(".skel", ".atlas", ".png"),
        )

        assertEquals(DocumentPickPurpose.ASSET_FILE, background.purpose)
        assertFalse(background.usesDirectoryTree)
        assertEquals(DocumentPickPurpose.ASSET_TREE, character.purpose)
        assertTrue(character.usesDirectoryTree)
        assertThrows(IllegalArgumentException::class.java) {
            DocumentPickRequest.fromBridge(
                requestId = "bad-character",
                purpose = "asset_file",
                assetKind = "character",
                allowedSuffixes = setOf(".skel"),
            )
        }
        assertThrows(IllegalArgumentException::class.java) {
            DocumentPickRequest.fromBridge(
                requestId = "bad-purpose",
                purpose = "desktop_browser",
                assetKind = "",
                allowedSuffixes = setOf(".txt"),
            )
        }
    }

    @Test
    fun staged_document_can_be_discarded_when_delivery_is_cancelled() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val root = context.cacheDir.resolve("incoming-test-${System.nanoTime()}")
        try {
            val store = IncomingFileStore(root)
            val incoming = store.stage(
                "story.txt",
                ByteArrayInputStream("content".toByteArray()),
                setOf(".txt"),
                100,
            )

            store.discard(incoming.token)

            assertFalse(root.resolve("incoming/${incoming.token}.bin").exists())
            assertFalse(root.resolve("incoming/${incoming.token}.json").exists())
        } finally {
            root.deleteRecursively()
        }
    }
}
