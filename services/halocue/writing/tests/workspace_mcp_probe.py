"""Official MCP client runs the simple conversational edit workflow."""

import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    config = json.loads(sys.argv[1])
    async with stdio_client(StdioServerParameters(**config)) as (r, w):
        async with ClientSession(r, w) as host:
            await host.initialize()
            tools = await host.list_tools()
            assert len(tools.tools) == 8
            for tool in tools.tools:
                assert tool.outputSchema
                properties = tool.inputSchema["properties"]
                assert (
                    not {"work_id", "base_revision_id", "replace_proposal_id", "old_text_sha256"}
                    & properties.keys()
                )

            async def call(name, args=None):
                response = await host.call_tool(name, args or {})
                assert not response.isError, response.content
                return response.structuredContent

            found = await call("halocue_find_scenes")
            scene = found["scenes"][0]
            assert scene["view_url"].startswith("http://127.0.0.1:")
            scene_id = scene["scene_id"]
            materials = await call(
                "halocue_search_materials", {"scene_id": scene_id, "query": "爱丽丝"}
            )
            assert materials["items"]
            card = materials["items"][0]["content"]
            window = await call("halocue_read_scene", {"scene_id": scene_id, "limit": 1})
            assert window["source"] == "saved_manuscript"
            tail = await call(
                "halocue_read_scene", {"scene_id": scene_id, "start": window["next_start"]}
            )
            # Stable read-only answers for workspace-mcp-evaluation.xml. These
            # SDK checks do not claim an external LLM evaluation.
            checks = [
                (window["total_paragraphs"], 2),
                (window["paragraphs"][0]["text"], "窗外下着一场雨。"),
                (window["paragraphs"][0]["type"], "narration"),
                (tail["paragraphs"][0]["speaker"], "爱丽丝"),
                (tail["paragraphs"][0]["text"], "提示灯亮了。"),
                (card["name"], "爱丽丝"),
                (card["ooc_constraints"][0], "不替别人猜测动机"),
                (card["voice_anchors"][0], "先确认眼前的情况。"),
                (tail["paragraphs"][0]["paragraph"], 2),
                (window["source"], "saved_manuscript"),
            ]
            assert all(actual == expected for actual, expected in checks)
            args = {
                "read_id": window["read_id"],
                "edits": [{"paragraph": 1, "text": "窗外雨声渐轻。"}],
            }
            submitted = await call("halocue_propose_scene_edit", args)
            assert submitted["status"] == "pending"
            assert (await call("halocue_propose_scene_edit", args))["duplicate"]
            pending = await call("halocue_read_scene", {"scene_id": scene_id})
            assert pending["source"] == "pending_candidate"
            assert pending["paragraphs"][0]["text"] == "窗外雨声渐轻。"
            refined = await call(
                "halocue_propose_scene_edit",
                {
                    "read_id": pending["read_id"],
                    "edits": [{"paragraph": 1, "text": "窗外细雨未歇。"}],
                },
            )
            assert refined["status"] == "pending"
            rejected = await host.call_tool(
                "halocue_propose_scene_edit",
                args | {"edits": [{"paragraph": 2, "text": "未读取不能改。"}]},
            )
            assert rejected.isError
            print(
                json.dumps(
                    {
                        "direct_workflow": True,
                        "tools": len(tools.tools),
                        "refinement": True,
                        "read_only_checks": len(checks),
                    }
                )
            )


asyncio.run(main())
