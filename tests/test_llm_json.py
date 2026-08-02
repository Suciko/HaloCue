from llm import parse_json_response


def test_parse_json_response_accepts_bare_json():
    assert parse_json_response('{"lines":[]}') == {"lines": []}


def test_parse_json_response_strips_a_complete_markdown_json_fence():
    text = "```json\n{\n  \"lines\": []\n}\n```"

    assert parse_json_response(text) == {"lines": []}
