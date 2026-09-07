import json
import subprocess
from pathlib import Path


def render(usage):
    source = (Path(__file__).resolve().parents[1] / "web/app.js").read_text(encoding="utf-8")
    begin = source.index("function compactTokenCount(")
    end = source.index("function agentRuntimeBarMarkup(", begin)
    script = (
        "const esc=String;"
        + source[begin:end]
        + "\nconsole.log(JSON.stringify(agentUsageMarkup("
        + json.dumps(usage)
        + ")));"
    )
    result = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, encoding="utf-8", check=True
    )
    return json.loads(result.stdout)


def test_missing_usage_is_not_known_zero_or_cache_miss():
    html = render(
        {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "usage_status": "not_reported",
            "cache_status": "unknown",
        }
    )
    assert "未报告" in html
    assert "缓存未命中" not in html
    assert "输入" not in html


def test_partial_cost_is_labeled_as_known_subtotal():
    html = render(
        {
            "input_tokens": 10,
            "output_tokens": 0,
            "estimated_cost": 0.01,
            "usage_status": "partial",
            "cost_status": "partial",
            "cache_status": "unknown",
        }
    )
    assert "统计不完整" in html
    assert "已报告部分" in html
    assert "$0.01" in html


def test_unsupported_cache_is_not_a_reported_miss():
    html = render(
        {
            "input_tokens": 10,
            "output_tokens": 2,
            "cache_read_tokens": 0,
            "usage_status": "reported",
            "cache_status": "unsupported",
        }
    )
    assert "不支持缓存" in html
    assert "缓存未命中" not in html


def test_live_scene_proposal_details_show_partial_cost():
    source = (Path(__file__).resolve().parents[1] / "web/app.js").read_text(encoding="utf-8")
    helpers = source[
        source.index("function compactTokenCount(") : source.index(
            "function agentRuntimeBarMarkup("
        )
    ]
    renderer = source[
        source.index("function sceneProposalRuntimeMarkup(") : source.index(
            "function sceneProposalImpactMarkup("
        )
    ]
    usage = {
        "input_tokens": 10,
        "output_tokens": 2,
        "estimated_cost": 0.01,
        "usage_status": "partial",
        "cost_status": "partial",
        "cache_status": "unknown",
    }
    script = (
        "const esc=String;const state={work:{agent_runs:[{id:'run',proposal_id:'proposal',policy:{usage:"
        + json.dumps(usage)
        + "}}]},capabilities:{providers:[]}};"
        + helpers
        + renderer
        + "console.log(sceneProposalRuntimeMarkup({id:'proposal'}));"
    )
    result = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, encoding="utf-8", check=True
    )
    assert "运行详情" in result.stdout
    assert "已报告部分" in result.stdout
    assert "统计不完整" in result.stdout
    assert "费用估算" not in result.stdout


def test_live_failed_conversation_details_do_not_report_zero_consumption():
    source = (Path(__file__).resolve().parents[1] / "web/app.js").read_text(encoding="utf-8")
    helpers = source[
        source.index("function compactTokenCount(") : source.index(
            "function agentRuntimeBarMarkup("
        )
    ]
    renderer = source[
        source.index("function workAgentToolMarkup(") : source.index(
            "function compactParagraphNumber("
        )
    ]
    script = (
        """const esc=String;const agentRunForMessage=()=>({id:'run',status:'failed',tool_calls:[],policy:{usage:{usage_status:'not_reported',input_tokens:0,output_tokens:0}},failure:{}});
    const agentFailureView=()=>({title:'failed',message:'synthetic',action:'retry'});const agentFailureNeedsRecovery=()=>true;
    """
        + helpers
        + renderer
        + "console.log(workAgentToolMarkup({},{}));"
    )
    result = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, encoding="utf-8", check=True
    )
    assert "技术详情" in result.stdout
    assert "不代表零消耗" in result.stdout


def test_live_details_prefer_physical_retry_summary_to_last_response():
    source = (Path(__file__).resolve().parents[1] / "web/app.js").read_text(encoding="utf-8")
    helpers = source[
        source.index("function compactTokenCount(") : source.index(
            "function agentRuntimeBarMarkup("
        )
    ]
    renderer = source[
        source.index("function sceneProposalRuntimeMarkup(") : source.index(
            "function sceneProposalImpactMarkup("
        )
    ]
    observed = {
        "physical_request_count": 2,
        "logical_request_count": 1,
        "unknown_usage_count": 1,
        "pending_count": 0,
        "totals": {
            "input_tokens": 10,
            "output_tokens": 2,
            "estimated_cost": 0.01,
            "usage_status": "partial",
            "cost_status": "partial",
            "cache_status": "unknown",
        },
    }
    run = {
        "id": "run",
        "proposal_id": "proposal",
        "policy": {
            "usage": {
                "estimated_cost": 0.01,
                "usage_status": "reported",
                "cost_status": "complete_estimate",
            }
        },
        "request_usage": observed,
    }
    script = (
        "const esc=String;const state="
        + json.dumps({"work": {"agent_runs": [run]}, "capabilities": {"providers": []}})
        + ";"
        + helpers
        + renderer
        + "console.log(sceneProposalRuntimeMarkup({id:'proposal'}));"
    )
    result = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, encoding="utf-8", check=True
    )
    assert "HTTP 请求 2" in result.stdout
    assert "1 次未报告用量" in result.stdout
    assert "已报告部分" in result.stdout
