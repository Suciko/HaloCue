"""Interaction regression for the graph module, without accounts or user projects."""

import os
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "web"
NODES = [
    {"id": "character:akari", "type": "character", "label": "明里", "meta": "已确认 · 当前修订"},
    {"id": "character:natsu", "type": "character", "label": "夏澄", "meta": "已确认 · 当前修订"},
    {"id": "character:rin", "type": "character", "label": "凛", "meta": "已确认 · 当前修订"},
    {"id": "entity:club", "type": "entity", "label": "旧校舍调查社", "meta": "已确认 · 当前修订"},
    {"id": "entity:room", "type": "entity", "label": "封存的档案室", "meta": "已确认 · 当前修订"},
    {"id": "rule:night", "type": "rule", "label": "夜间通行规则", "meta": "已确认 · 当前修订"},
    {"id": "event:signal", "type": "event", "label": "来自旧楼的信号", "meta": "已确认 · 当前修订"},
    {"id": "fact:letter", "type": "fact", "label": "未寄出的信", "meta": "已确认 · 当前修订"},
]
EDGES = [
    {
        "from": NODES[a]["id"],
        "to": NODES[b]["id"],
        "kind": kind,
        "summary": "合成验收资料，不来自用户作品。",
    }
    for a, b, kind in [
        (0, 1, "搭档"),
        (0, 2, "同学"),
        (0, 3, "社团成员"),
        (1, 3, "社团成员"),
        (2, 4, "发现"),
        (3, 4, "调查地点"),
        (4, 5, "受约束"),
        (4, 6, "发生于"),
        (6, 7, "线索"),
    ]
]


@pytest.fixture(scope="module")
def browser():
    driver = pytest.importorskip("playwright.sync_api")
    with driver.sync_playwright() as p:
        instance = p.chromium.launch()
        yield instance
        instance.close()


@pytest.fixture
def page(browser):
    page = browser.new_page(viewport={"width": 1280, "height": 960}, device_scale_factor=1)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.set_content("""<!doctype html><html lang="zh-CN" data-theme="light"><meta charset="utf-8"><style>
    :root{--hc-bg:#f6f8fa;--hc-panel:#fff;--hc-line:#dde5e9;--hc-muted:#71838b;--hc-text:#243940;--hc-accent:#277f78;--hc-selected:#e7f2ee;--hc-hover:#eef4f5;font-family:"Microsoft YaHei",sans-serif}
    html[data-theme="dark"]{--hc-bg:#172129;--hc-panel:#1d2a33;--hc-line:#34434e;--hc-muted:#98abb7;--hc-text:#dfebee;--hc-accent:#7bd0c2;--hc-selected:#283e43;--hc-hover:#2a3942}
    *{box-sizing:border-box}body{margin:0;background:var(--hc-bg);padding:40px}button,input{font:inherit}#app{max-width:1120px;margin:auto}h1{font-size:24px;color:var(--hc-text);margin:0 0 8px}header p{font-size:13px;color:var(--hc-muted);margin:0 0 24px}.graph-toolbar{display:flex}.segmented-control{display:flex} @media(max-width:760px){body{padding:12px}}
    </style><div id="app" class="hc-redesign library-stage"><header><h1>作品知识图</h1><p>人物与世界的连接，只来自已保存的正式修订。</p></header><main id="host"></main></div></html>""")
    page.add_style_tag(path=str(WEB / "knowledge-graph-ui.css"))
    page.add_script_tag(path=str(WEB / "vendor/echarts/echarts-6.0.0.min.js"))
    page.add_script_tag(path=str(WEB / "knowledge-graph-ui.js"))
    page.evaluate(
        """data => {
      window.fixture=data; window.clicks=0; window.focusId='';
      window.paint = (focus='') => {window.focusId=focus; const host=document.querySelector('#host');
        host.innerHTML='<div class="graph-toolbar"><div class="segmented-control"><button class="active" data-return>全部</button><button>人物</button><button>世界观</button><button>规则</button><button>事件与事实</button></div></div><section class="knowledge-map"></section>';
        HaloCueKnowledgeGraph.upgrade(host,{...fixture,focusId:focus});
      };
      document.querySelector('#host').addEventListener('click',e=>{const node=e.target.closest('[data-graph-node]'); if(node){clicks++;paint(node.dataset.graphNode)} if(e.target.closest('[data-return]'))paint()});
      paint();
    }""",
        {"nodes": NODES, "edges": EDGES},
    )
    page.wait_for_timeout(600)
    yield page
    assert not errors, errors
    page.close()


def test_full_workbench_projection_focus_and_source_edit(browser, tmp_path):
    import threading
    from http.server import ThreadingHTTPServer
    from halocue_writing.app import make_handler
    from halocue_writing.service import WritingService
    from playwright.sync_api import expect

    service = WritingService(tmp_path)
    service.start()
    work = service.create_work({"title": "旧校舍来信 · 图谱验收", "world_seed": "blank"})
    work_id = work["id"]

    def version():
        return service.get_work(work_id)["version"]

    cards = []
    for name in ["明里", "夏澄", "凛"]:
        saved = service.save_character_card(
            work_id,
            {
                "expected_version": version(),
                "name": name,
                "source_type": "custom",
                "trust_status": "confirmed",
                "source_refs": ["合成验收资料"],
                "relationships": [
                    {
                        "target_character_id": card,
                        "kind": "同社团",
                        "summary": "一起调查旧楼的信号。",
                    }
                    for card in cards
                ],
            },
        )
        cards.append(saved["card_id"])
    service.save_world_bible(
        work_id,
        {
            "expected_version": version(),
            "title": "旧楼档案",
            "source_type": "custom",
            "entities": [
                {
                    "id": "club",
                    "name": "旧校舍调查社",
                    "kind": "organization",
                    "summary": "调查小组",
                    "source": "合成验收资料",
                    "confidence_status": "confirmed",
                    "participant_character_ids": cards,
                },
                {
                    "id": "archive",
                    "name": "封存的档案室",
                    "kind": "place",
                    "summary": "发现线索的地方",
                    "source": "合成验收资料",
                    "confidence_status": "confirmed",
                    "participant_character_ids": [cards[2]],
                },
            ],
            "rules": [],
            "timeline": [
                {
                    "id": "signal",
                    "text": "来自旧楼的信号",
                    "category": "当前剧情",
                    "source": "合成验收资料",
                    "confidence_status": "confirmed",
                    "participant_character_ids": cards[:2],
                }
            ],
        },
    )
    before = version()
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service, WEB))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    page = browser.new_page(viewport={"width": 1440, "height": 1080})
    errors = []
    external = []

    def route(request):
        if request.request.url.startswith(
            ("http:", "https:")
        ) and not request.request.url.startswith("http://127.0.0.1:"):
            external.append(request.request.url)
            request.abort()
        else:
            request.continue_()

    page.route("**/*", route)
    page.on("pageerror", lambda e: errors.append(str(e)))
    try:
        page.goto(
            f"http://127.0.0.1:{server.server_port}/?section=references&view=relations&work_id={work_id}"
        )

        expect(page.locator(".graph-summary-list")).to_be_visible()
        graph_url = page.url
        # A relation summary must route using both endpoints, not just its character source.
        for target, lens in [("旧校舍调查社", "世界关联"), ("来自旧楼的信号", "剧情线索")]:
            page.locator(".graph-summary-row").filter(has_text=target).first.click()
            expect(page.locator(".graph-lens-tabs .active")).to_have_text(lens)
            expect(page.locator(".kg-index-node").filter(has_text=target)).to_have_count(1)
            page.locator(".kg-index summary").click()
            # Focusing the person within that lens must not discard the world/event relation.
            page.locator(".kg-index-node.kg-character").first.click()
            expect(page.locator(".graph-lens-tabs .active")).to_have_text(lens)
            expect(page.locator(".kg-index-node").filter(has_text=target)).to_have_count(1)
            assert version() == before
            page.goto(graph_url)
            expect(page.locator(".graph-summary-list")).to_be_visible()
        page.get_by_role("button", name="展开关系图", exact=True).click()
        expect(page.locator(".kg-index-node")).to_have_count(3)
        assert chart_eval(page, "chart.getModel().getSeriesByIndex(0).getEdgeData().count()") == 3
        page.wait_for_timeout(350)
        assert (
            page.locator(".kg-search").evaluate("el=>getComputedStyle(el).flexDirection") == "row"
        )
        search_box = page.locator(".kg-search").bounding_box()
        assert search_box["height"] < 50
        out = os.environ.get("HALOCUE_GRAPH_SCREENSHOTS")
        if out:
            page.screenshot(path=str(Path(out) / "workbench-light.png"), full_page=True)
        page.get_by_role("button", name="冻结布局", exact=True).click()
        click_node(page)
        expect(page.locator('.kg-index-node[aria-pressed="true"]')).to_have_count(1)
        expect(page.locator(".kg-detail")).to_be_visible()
        page.locator("[data-open-graph-source]").click()
        expect(page.locator("#libraryCharacterForm")).to_be_visible()
        page.goto(
            f"http://127.0.0.1:{server.server_port}/?section=references&view=relations&work_id={work_id}"
        )
        page.get_by_role("button", name="展开关系图", exact=True).click()
        expect(page.locator(".kg-index-node")).to_have_count(3)
        page.get_by_role("button", name="世界关联", exact=True).click()
        expect(page.locator(".kg-index-node")).to_have_count(5)
        page.evaluate("document.documentElement.dataset.theme='dark'")
        page.wait_for_timeout(350)
        page.wait_for_timeout(800)
        if out:
            page.locator(".knowledge-map").screenshot(path=str(Path(out) / "workbench-dark.png"))
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(150)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        if out:
            page.locator(".kg-viewport").scroll_into_view_if_needed()
            page.screenshot(path=str(Path(out) / "workbench-mobile.png"), full_page=True)
        assert version() == before, "Exploring the graph must not create revisions"
        assert not errors, errors
        assert not external, external
        assert "RELATION ATLAS" not in page.locator(".knowledge-map").inner_text()
        assert "每条关系" not in page.locator(".knowledge-map").inner_text()
    finally:
        page.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        service.close()


def chart_eval(page, expression):
    return page.evaluate(
        """expression => {
      const chart=echarts.getInstanceByDom(document.querySelector('[data-kg-chart]'));
      return Function('chart', 'return ('+expression+')')(chart);
    }""",
        expression,
    )


def node_positions(page):
    return chart_eval(
        page,
        """(()=>{const data=chart.getModel().getSeriesByIndex(0).getData();
    return Array.from({length:data.count()},(_,i)=>({id:data.getId(i),point:data.getItemLayout(i).slice(),pixel:chart.convertToPixel({seriesIndex:0},data.getItemLayout(i))}));})()""",
    )


def click_node(page, index=0):
    page.locator("[data-kg-viewport]").scroll_into_view_if_needed()
    page.wait_for_timeout(60)
    point = node_positions(page)[index]["pixel"]
    bounds = page.locator("[data-kg-chart]").bounding_box()
    page.mouse.click(bounds["x"] + point[0], bounds["y"] + point[1])


def test_force_visuals(page):
    assert chart_eval(page, "chart.getOption().series[0].layout") == "force"
    assert chart_eval(page, "chart.getOption().series[0].edgeLabel.show") is False
    assert chart_eval(page, "chart.getOption().series[0].emphasis.edgeLabel.show") is True
    assert chart_eval(page, "chart.getModel().getSeriesByIndex(0).getData().count()") == 8
    page.wait_for_timeout(6200)
    page.get_by_role("button", name="适应画布", exact=True).click()
    page.wait_for_timeout(100)
    out = os.environ.get("HALOCUE_GRAPH_SCREENSHOTS")
    if out:
        output = Path(out)
        output.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(output / "force-light.png"), full_page=True)
        page.evaluate("document.documentElement.dataset.theme='dark'")
        assert chart_eval(page, "chart.getOption().series[0].force.layoutAnimation") is True
        page.wait_for_timeout(120)
        page.screenshot(path=str(output / "force-dark.png"), full_page=True)
        click_node(page)
        page.wait_for_timeout(2200)
        page.screenshot(path=str(output / "force-focus.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(200)
        page.screenshot(path=str(output / "force-mobile.png"), full_page=True)


def test_drag_moves_neighbors_and_does_not_open_details(page):
    # Let the native solver cool down; dragging must reheat it, not merely pan a card.
    page.wait_for_timeout(6200)
    before = node_positions(page)
    point = before[0]["pixel"]
    bounds = page.locator("[data-kg-chart]").bounding_box()
    page.mouse.move(bounds["x"] + point[0], bounds["y"] + point[1])
    page.mouse.down()
    page.mouse.move(bounds["x"] + point[0] + 65, bounds["y"] + point[1] + 40, steps=16)
    page.wait_for_timeout(160)
    page.mouse.up()
    page.wait_for_timeout(350)
    after = node_positions(page)
    assert page.evaluate("clicks") == 0
    assert sum(a["point"] != b["point"] for a, b in zip(before, after)) > 1
    assert page.evaluate("fixture.edges") == EDGES
    page.wait_for_timeout(250)
    click_node(page)
    assert page.evaluate("clicks") == 1
    assert page.locator(".kg-detail").is_visible()


def test_freeze_resume_fit_and_keyboard_zoom(page):
    freeze = page.get_by_role("button", name="冻结布局", exact=True)
    freeze.click()
    assert chart_eval(page, "chart.getOption().series[0].layout") == "none"
    first = node_positions(page)
    page.wait_for_timeout(400)
    assert node_positions(page) == first
    viewport = page.locator("[data-kg-viewport]")
    viewport.focus()
    zoom = chart_eval(page, "chart.getOption().series[0].zoom")
    viewport.press("+")
    assert chart_eval(page, "chart.getOption().series[0].zoom") > zoom
    viewport.press("-")
    assert abs(chart_eval(page, "chart.getOption().series[0].zoom") - zoom) < 0.001
    viewport.press("ArrowLeft")
    viewport.press("0")
    width = page.locator("[data-kg-chart]").bounding_box()["width"]
    for node in node_positions(page):
        assert 20 < node["pixel"][0] < width - 20
    page.get_by_role("button", name="继续布局", exact=True).click()
    assert chart_eval(page, "chart.getOption().series[0].layout") == "force"


def test_search_labels_hover_and_accessible_navigation(page):
    page.get_by_role("button", name="冻结布局", exact=True).click()
    search = page.get_by_role("searchbox", name="查找图中节点")
    search.fill("档案")
    assert page.locator("[data-kg-search-count]").inner_text() == "1 个匹配"
    search.fill("完全不存在")
    assert page.locator("[data-kg-search-count]").inner_text() == "0 个匹配"
    search.press("Escape")
    assert search.input_value() == ""
    assert chart_eval(page, "chart.getOption().series[0].edgeLabel.show") is False
    toggle = page.get_by_role("button", name="显示关系名", exact=True)
    toggle.click()
    assert chart_eval(page, "chart.getOption().series[0].edgeLabel.show") is True
    toggle = page.get_by_role("button", name="隐藏关系名", exact=True)
    toggle.click()
    assert chart_eval(page, "chart.getOption().series[0].edgeLabel.show") is False
    point = node_positions(page)[0]["pixel"]
    bounds = page.locator("[data-kg-chart]").bounding_box()
    page.mouse.move(bounds["x"] + point[0], bounds["y"] + point[1])
    page.wait_for_timeout(100)
    state = chart_eval(
        page,
        "(()=>{const el=chart.getModel().getSeriesByIndex(0).getData().getItemGraphicEl(0);return {state:el.currentStates,hover:el.hoverState,child:el.childAt(0).currentStates,point:chart.convertToPixel({seriesIndex:0},chart.getModel().getSeriesByIndex(0).getData().getItemLayout(0))}})()",
    )
    assert state["hover"] == 2, state
    search.fill("明里")
    search.press("Enter")
    assert page.evaluate("focusId") == "character:akari"
    assert page.locator(".kg-index-node").count() == 4
    assert page.locator('.kg-index-node[aria-pressed="true"]').evaluate(
        "el=>el===document.activeElement"
    )


def test_reduce_motion_resize_and_no_horizontal_overflow(page):
    page.emulate_media(reduced_motion="reduce")
    page.wait_for_timeout(60)
    assert chart_eval(page, "chart.getOption().series[0].layout") == "none"
    assert chart_eval(page, "chart.getOption().animation") is False
    assert page.locator("[data-kg-motion]").is_disabled()
    page.set_viewport_size({"width": 360, "height": 800})
    page.wait_for_timeout(150)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert page.locator("[data-kg-labels]").get_attribute("aria-pressed") == "false"
    assert page.get_by_role("button", name="显示关系名", exact=True).is_visible()
    viewport_box = page.locator("[data-kg-viewport]").bounding_box()
    controls_box = page.locator(".kg-controls").bounding_box()
    assert controls_box["y"] >= viewport_box["y"] + viewport_box["height"] - 1
    page.get_by_role("button", name="适应画布", exact=True).click()
    bounds = page.locator("[data-kg-chart]").bounding_box()
    for node in node_positions(page):
        assert 15 < node["pixel"][0] < bounds["width"] - 15
        assert 30 < node["pixel"][1] < bounds["height"] - 75
    page.set_viewport_size({"width": 1280, "height": 960})
    page.wait_for_timeout(150)
    assert (
        abs(
            chart_eval(page, "chart.getWidth()")
            - page.locator("[data-kg-chart]").bounding_box()["width"]
        )
        < 1
    )


def test_empty_large_dangling_duplicate_names_and_loops(page):
    page.emulate_media(reduced_motion="reduce")
    page.evaluate("fixture={nodes:[],edges:[]};paint()")
    assert page.locator(".kg-empty").is_visible()
    assert page.locator(".kg-controls").count() == 0
    page.evaluate(
        """fixture={nodes:[{id:'a',type:'character',label:'同名'},{id:'b',type:'character',label:'同名'}],edges:[{from:'a',to:'b',kind:'关系一'},{from:'a',to:'b',kind:'关系二'},{from:'b',to:'a',kind:'反向'},{from:'a',to:'a',kind:'自己'},{from:'a',to:'missing'}]};paint()"""
    )
    assert chart_eval(page, "chart.getModel().getSeriesByIndex(0).getData().count()") == 2
    assert chart_eval(page, "chart.getModel().getSeriesByIndex(0).getEdgeData().count()") == 4
    assert page.locator("[data-kg-self-links] path").count() == 1
    page.evaluate(
        """fixture={nodes:Array.from({length:48},(_,i)=>({id:'n'+i,type:'character',label:'角色 '+i})),edges:[]};fixture.edges=fixture.nodes.slice(1).map(n=>({from:'n0',to:n.id,kind:'关系'}));paint()"""
    )
    assert chart_eval(page, "chart.getModel().getSeriesByIndex(0).getEdgeData().count()") == 47
    assert all(
        isinstance(value, (float, int)) for node in node_positions(page) for value in node["point"]
    )


def test_instance_cleanup_theme_change_and_safe_labels(page):
    page.evaluate(
        """window.oldCharts=[];for(let i=0;i<10;i++){oldCharts.push(echarts.getInstanceByDom(document.querySelector('[data-kg-chart]')));paint(i%2?'character:akari':'')}"""
    )
    assert page.evaluate("oldCharts.every(c=>c.isDisposed())")
    assert page.locator(".kg-force-chart canvas").count() == 1
    page.evaluate(
        """fixture.nodes[0].label='<img src=x onerror="window.injected=true">';fixture.edges[0].kind='<svg onload="window.injected=true">';paint()"""
    )
    assert page.locator(".knowledge-map img").count() == 0
    assert page.evaluate("window.injected") is None
    page.get_by_role("button", name="冻结布局", exact=True).click()
    positions = node_positions(page)
    color = chart_eval(page, "chart.getOption().series[0].data[0].itemStyle.borderColor")
    page.evaluate("document.documentElement.dataset.theme='dark'")
    page.wait_for_timeout(60)
    assert chart_eval(page, "chart.getOption().series[0].data[0].itemStyle.borderColor") != color
    assert [n["point"] for n in node_positions(page)] == [n["point"] for n in positions]
    # Removing the view must dispose the native engine and its force timer.
    page.evaluate(
        "window.lastChart=echarts.getInstanceByDom(document.querySelector('[data-kg-chart]'));document.querySelector('#host').innerHTML=''"
    )
    page.wait_for_timeout(100)
    assert page.evaluate("lastChart.isDisposed()")


def test_missing_engine_keeps_real_node_links_available(page):
    page.evaluate("window.echarts=undefined;paint()")
    assert page.locator(".kg-empty").is_visible()
    assert page.locator("[data-kg-index]").get_attribute("open") is not None
    assert page.locator(".kg-controls").is_hidden()
    page.locator(".kg-index-node").first.click()
    assert page.evaluate("clicks") == 1


def test_no_slogans_in_graph(page):
    text = page.locator(".knowledge-map").inner_text()
    for slogan in ["RELATION ATLAS", "每条关系", "展开故事", "故事的连接", "有来处"]:
        assert slogan not in text
    assert page.locator(".kg-heading").count() == 0
    assert chart_eval(page, "chart.getOption().series[0].label.position") == "inside"
    assert chart_eval(
        page, "chart.getOption().series[0].data.every(n=>n.symbol.startsWith('path://'))"
    )
    assert "节点大小表示关联数量" not in text
