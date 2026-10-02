"""Project-entry rendering and shared navigation guards; all data are synthetic."""

from pathlib import Path

import pytest
from playwright.sync_api import expect

WEB = Path(__file__).resolve().parents[1] / "web"


@pytest.fixture
def page():
    with pytest.importorskip("playwright.sync_api").sync_playwright() as driver:
        browser = driver.chromium.launch()
        page = browser.new_page()
        page.set_content('<main id="workspace"></main>')
        source = (WEB / "app.js").read_text(encoding="utf8")
        helpers = source[
            source.index("function projectRows()") : source.index(
                "registerAppClick(event=>{", source.index("function openProject(")
            )
        ]
        page.add_script_tag(
            content="""
          const state={works:[{id:'one',title:'First',updated_at:'2026-01-01'}, {id:'two',title:'Second',updated_at:'2026-02-01'}],work:{id:'one',title:'First',updated_at:'2026-01-01'}};
          const hcArray=v=>Array.isArray(v)?v:[];
          const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
          let hcNavigationEpoch=0;
          let hcLastWritingRoute={section:'writing',stage:'draft',sceneId:'s1',chapterId:'c1'};
          const calls=[];
          const loadWork=async(id)=>{calls.push(['load',id]);state.work={id};return true};
          const navigateRoute=(route)=>calls.push(['navigate',route]);
          const requestManuscriptNavigation=(callback)=>{calls.push(['guard']);};
          const routeLeavesManuscript=target=>target.section!=='writing'||target.stage!=='draft'||target.sceneId!=='s1';
          const toast=message=>calls.push(['error',message]);
        """
            + helpers
        )
        yield page
        browser.close()


def test_project_listing_uses_current_work_and_escapes_titles(page):
    page.evaluate(
        "state.work.title='<img src=x onerror=alert(1)>';state.work.updated_at='2026-03-01';renderProjects(document.querySelector('main'))"
    )
    expect(page.locator(".project-card")).to_have_count(2)
    expect(page.locator(".project-card h3").first).to_have_text("<img src=x onerror=alert(1)>")
    expect(page.locator(".project-card img")).to_have_count(0)
    assert page.evaluate("projectRows()[0].id") == "one"


@pytest.mark.parametrize("destination", ["works", "references", "structure", "draft", "release"])
def test_other_project_cannot_load_before_manuscript_confirmation(page, destination):
    page.evaluate(
        "destination=>{state.manuscriptDirty=true;openProject('two',destination)}", destination
    )
    assert page.evaluate("calls") == [["guard"]]
    assert page.evaluate("state.work.id") == "one"


def test_current_manuscript_can_be_reopened_without_discard_prompt(page):
    page.evaluate("state.manuscriptDirty=true;openProject('one','draft')")
    assert page.evaluate("calls") == [
        [
            "navigate",
            {
                "section": "writing",
                "stage": "draft",
                "sceneId": "s1",
                "chapterId": "c1",
                "pane": "writing",
            },
        ]
    ]


def test_unsaved_structure_does_not_silently_disappear_on_work_switch(page):
    page.evaluate("state.structureDirty=true;window.confirm=()=>false;openProject('two')")
    assert page.evaluate("calls") == []
    assert page.evaluate("state.work.id") == "one"


def test_production_review_destination_uses_the_shared_route(page):
    page.evaluate("openProject('two','release')")
    page.wait_for_function("calls.length===2")
    assert page.evaluate("calls[0]") == ["load", "two"]
    assert page.evaluate("calls[1][1].section") == "writing"
    assert page.evaluate("calls[1][1].stage") == "release"
