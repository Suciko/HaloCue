from pathlib import Path

import pytest
from playwright.sync_api import expect


@pytest.fixture
def page():
    with pytest.importorskip("playwright.sync_api").sync_playwright() as driver:
        browser = driver.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        yield page
        browser.close()


WEB = Path(__file__).resolve().parents[1] / "web"


def test_feedback_context_checkbox_controls_work_and_error_identifiers(page):
    source = (WEB / "app.js").read_text(encoding="utf8")
    helper = source[
        source.index("function feedbackSubmissionPayload(") : source.index(
            "function openFeedbackDialog(", source.index("function feedbackSubmissionPayload(")
        )
    ]
    page.set_content(
        """
        <form id="feedbackForm">
          <select name="category"><option value="bug">功能出错</option></select>
          <input name="summary" value="按钮没有响应">
          <textarea name="details">点击后没有变化。</textarea>
          <select name="severity"><option value="major">明显影响当前任务</option></select>
          <input type="checkbox" name="attach_context" checked>
        </form>
        """
    )
    page.add_script_tag(content=helper)
    with_context = page.evaluate(
        """feedbackSubmissionPayload(
          new FormData(document.querySelector('#feedbackForm')),
          {workId:'work-1', context:{stage:'draft'}, error:{code:'provider_failed'}}
        )"""
    )
    assert with_context["work_id"] == "work-1"
    assert with_context["context"] == {"stage": "draft"}
    assert with_context["error"] == {"code": "provider_failed"}

    page.locator('[name="attach_context"]').uncheck()
    without_context = page.evaluate(
        """feedbackSubmissionPayload(
          new FormData(document.querySelector('#feedbackForm')),
          {workId:'work-1', context:{stage:'draft'}, error:{code:'provider_failed'}}
        )"""
    )
    assert without_context["work_id"] is None
    assert without_context["context"] == {}
    assert without_context["error"] == {}
    expect(page.locator('[name="attach_context"]')).not_to_be_checked()
