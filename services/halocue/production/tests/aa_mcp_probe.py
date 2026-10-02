"""External-host SDK check; no LLM or provider request."""

import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    config, run_id = json.loads(sys.argv[1]), sys.argv[2]
    async with stdio_client(StdioServerParameters(**config)) as (r, w):
        async with ClientSession(r, w) as host:
            await host.initialize()
            tools = await host.list_tools()
            assert len(tools.tools) == 8
            for tool in tools.tools:
                assert tool.outputSchema
                assert (
                    not {"expected_draft_version", "card_id", "connection_id"}
                    & tool.inputSchema["properties"].keys()
                )

            async def call(name, **args):
                response = await host.call_tool(name, args)
                assert not response.isError, response.content
                return response.structuredContent

            found = await call("halocue_find_productions")
            assert found["productions"][0]["run_id"] == run_id
            assert found["productions"][0]["view_url"].startswith(config["args"][-1])
            window = await call("halocue_read_production", run_id=run_id, query="提示灯")
            full = await call("halocue_read_production", run_id=run_id)
            number = window["cards"][0]["card"]
            resources = await call(
                "halocue_search_production_resources",
                run_id=run_id,
                kind="character_details",
                character="alice",
            )
            assert resources["character"]["faces"][1]["id"] == "01"
            lines = [c for c in full["cards"] if c["kind"] == "line"]
            answers = [
                str(found["total"]),
                str(full["total_cards"]),
                str(lines[0]["card"]),
                lines[0]["fields"]["who"],
                lines[0]["fields"]["text"],
                lines[1]["fields"]["text"],
                full["cast"]["爱丽丝"]["id"],
                str(len(resources["character"]["faces"])),
                resources["character"]["faces"][1]["id"],
                resources["character"]["faces"][1]["semantic_cn"],
            ]
            assert answers == [
                "1",
                "4",
                "3",
                "爱丽丝",
                "提示灯亮了。",
                "先确认眼前的情况。",
                "alice",
                "2",
                "01",
                "认真",
            ]
            args = {
                "read_id": window["read_id"],
                "edits": [
                    {"card": number, "operation": "update", "fields": {"face": "01"}},
                    {
                        "card": number,
                        "operation": "insert_after",
                        "fields": {"cmd": "wait", "arg": "500"},
                    },
                ],
            }
            receipt = await call("halocue_propose_performance_edit", **args)
            duplicate = await call("halocue_propose_performance_edit", **args)
            assert receipt["state"] == "pending" and duplicate["duplicate"]
            assert receipt["proposal_id"] == duplicate["proposal_id"]
            print(
                json.dumps(
                    {
                        "aa_workflow": True,
                        "tools": 8,
                        "proposal_id": receipt["proposal_id"],
                        "read_only_evaluation_answers": answers,
                    }
                )
            )


asyncio.run(main())
