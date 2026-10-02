"""Official SDK stdio round trip with synthetic task data, no model inference."""

import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    params = StdioServerParameters(
        command=sys.executable,
        args=[sys.argv[1], "--connection", sys.argv[2], "--endpoint", sys.argv[3]],
        env={"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as client:
            await client.initialize()
            tools = await client.list_tools()
            assert len(tools.tools) == 5
            assert not any("apply" in t.name for t in tools.tools)
            task = await client.call_tool("halocue_get_task")
            assert not task.isError
            package = task.structuredContent
            window = await client.call_tool("halocue_read_scene_window", {"offset": 0, "limit": 1})
            assert not window.isError, window.content
            assert window.structuredContent is not None, window.model_dump()
            assert (
                window.structuredContent["blocks"][0]["id"] == package["source"]["blocks"][0]["id"]
            )
            cards = await client.call_tool("halocue_read_character_cards")
            assert isinstance(cards.structuredContent["character_cards"], list)
            resource = await client.read_resource("halocue://task")
            assert json.loads(resource.contents[0].text)["task_id"] == package["task_id"]
            empty_window = await client.call_tool(
                "halocue_read_scene_window", {"offset": 1, "limit": 40}
            )
            status = await client.call_tool("halocue_get_task_status")
            # Ten stable, read-only fixture evaluation answers, before submission.
            checks = [
                (package["kind"], "scene.text.edit"),
                (window.structuredContent["total"], 1),
                (package["source"]["total_blocks"], 2),
                (window.structuredContent["blocks"][0]["id"], "block-a"),
                (window.structuredContent["blocks"][0]["type"], "narration"),
                (window.structuredContent["blocks"][0]["text"], "窗外下着一场雨。"),
                (cards.structuredContent["character_cards"][0]["name"], "爱丽丝"),
                (
                    cards.structuredContent["character_cards"][0]["ooc_constraints"][0],
                    "不替别人猜测动机",
                ),
                (len(empty_window.structuredContent["blocks"]), 0),
                (status.structuredContent["status"], "open"),
            ]
            assert all(actual == expected for actual, expected in checks)
            invalid = await client.call_tool("halocue_submit_result", {"result": {"apply": True}})
            assert invalid.isError
            block = package["source"]["blocks"][0]
            result = {
                "schema_version": "external-agent-result/1.0",
                "task_id": package["task_id"],
                "input_hash": package["input_hash"],
                "base_revision_id": package["scope"]["base_revision_id"],
                "reason": "Synthetic MCP edit",
                "edits": [
                    {
                        "block_id": block["id"],
                        "old_text_sha256": block["text_sha256"],
                        "new_text": "窗外雨声渐轻。",
                    }
                ],
            }
            submitted = await client.call_tool("halocue_submit_result", {"result": result})
            assert not submitted.isError
            duplicate = await client.call_tool("halocue_submit_result", {"result": result})
            assert duplicate.structuredContent["duplicate"] is True
            status = await client.call_tool("halocue_get_task_status")
            assert status.structuredContent["status"] == "submitted"
            print(
                json.dumps(
                    {
                        "proposal_created": bool(submitted.structuredContent["proposal_id"]),
                        "read_only_checks": len(checks),
                    }
                )
            )


asyncio.run(main())
