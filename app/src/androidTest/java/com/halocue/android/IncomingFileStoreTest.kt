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

    @Test
    fun stages_a_bounded_private_directory_tree() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val root = context.cacheDir.resolve("incoming-tree-test-${System.nanoTime()}")
        try {
            val store = IncomingFileStore(root)
            val result = store.stageTree(
                displayName = "../../Arona",
                entries = listOf(
                    IncomingTreeEntry("Arona.skel") {
                        ByteArrayInputStream("skeleton".toByteArray())
                    },
                    IncomingTreeEntry("Arona.atlas") {
                        ByteArrayInputStream("Arona.png\n".toByteArray())
                    },
                    IncomingTreeEntry("textures/Arona.png") {
                        ByteArrayInputStream(byteArrayOf(1, 2, 3))
                    },
                ),
                allowedSuffixes = setOf(".skel", ".atlas", ".png"),
                maxFiles = 10,
                maxFileBytes = 100,
                maxTotalBytes = 200,
            )

            assertEquals("Arona", result.name)
            assertEquals(3, result.fileCount)
            assertEquals(21L, result.size)
            assertEquals(
                "skeleton",
                root.resolve("incoming/${result.token}.tree/Arona.skel").readText(),
            )
            assertTrue(root.resolve("incoming/${result.token}.tree.json").isFile)
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun directory_traversal_filters_non_asset_files_by_suffix() {
        assertTrue(hasAllowedDocumentSuffix("Arona.SKEL", setOf(".skel", ".atlas")))
        assertTrue(hasAllowedDocumentSuffix("textures/Arona.png", setOf(".png")))
        assertFalse(hasAllowedDocumentSuffix(".nomedia", setOf(".png", ".skel")))
        assertFalse(hasAllowedDocumentSuffix("README.txt", setOf(".png", ".skel")))
    }

    @Test
    fun rejects_unsafe_duplicate_and_oversized_tree_entries_without_residue() {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val root = context.cacheDir.resolve("incoming-tree-test-${System.nanoTime()}")
        try {
            val store = IncomingFileStore(root)
            val unsafe = assertThrows(IncomingFileStoreException::class.java) {
                store.stageTree(
                    "unsafe",
                    listOf(IncomingTreeEntry("../outside.png") {
                        ByteArrayInputStream(byteArrayOf(1))
                    }),
                    setOf(".png"),
                    maxFiles = 2,
                    maxFileBytes = 2,
                    maxTotalBytes = 2,
                )
            }
            assertEquals("unsafe_tree_path", unsafe.code)

            val duplicate = assertThrows(IncomingFileStoreException::class.java) {
                store.stageTree(
                    "duplicate",
                    listOf(
                        IncomingTreeEntry("A.png") { ByteArrayInputStream(byteArrayOf(1)) },
                        IncomingTreeEntry("a.png") { ByteArrayInputStream(byteArrayOf(2)) },
                    ),
                    setOf(".png"),
                    maxFiles = 2,
                    maxFileBytes = 2,
                    maxTotalBytes = 2,
                )
            }
            assertEquals("duplicate_tree_path", duplicate.code)

            val oversized = assertThrows(IncomingFileStoreException::class.java) {
                store.stageTree(
                    "large",
                    listOf(IncomingTreeEntry("large.png") {
                        ByteArrayInputStream(byteArrayOf(1, 2, 3))
                    }),
                    setOf(".png"),
                    maxFiles = 2,
                    maxFileBytes = 2,
                    maxTotalBytes = 4,
                )
            }
            assertEquals("file_too_large", oversized.code)

            val tooMany = assertThrows(IncomingFileStoreException::class.java) {
                store.stageTree(
                    "many",
                    listOf(
                        IncomingTreeEntry("one.png") { ByteArrayInputStream(byteArrayOf(1)) },
                        IncomingTreeEntry("two.png") { ByteArrayInputStream(byteArrayOf(2)) },
                    ),
                    setOf(".png"),
                    maxFiles = 1,
                    maxFileBytes = 2,
                    maxTotalBytes = 4,
                )
            }
            assertEquals("too_many_files", tooMany.code)

            val totalTooLarge = assertThrows(IncomingFileStoreException::class.java) {
                store.stageTree(
                    "total",
                    listOf(
                        IncomingTreeEntry("one.png") { ByteArrayInputStream(byteArrayOf(1, 2)) },
                        IncomingTreeEntry("two.png") { ByteArrayInputStream(byteArrayOf(3, 4)) },
                    ),
                    setOf(".png"),
                    maxFiles = 2,
                    maxFileBytes = 3,
                    maxTotalBytes = 3,
                )
            }
            assertEquals("tree_too_large", totalTooLarge.code)
            assertTrue(root.resolve("incoming").listFiles().isNullOrEmpty())
        } finally {
            root.deleteRecursively()
        }
    }
}
