"""Create original, fictional sample data only in a fresh reviewer workspace."""


def create_review_sample(service):
    if not service.provider.is_simulation:
        raise ValueError("Sample creation requires the local simulation provider")
    work = service.create_work({"title": "协作者验收样例（虚构）"})

    def version():
        return service.get_work(work["id"])["version"]

    service.save_brief(
        work["id"],
        {
            "expected_version": version(),
            "idea": "两位档案员检查不同房间",
            "mode": "bond_short",
            "characters": ["白露", "青禾"],
        },
    )
    service.generate_blueprint(work["id"], {"expected_version": version()})
    cards = []
    for name in ["白露", "青禾"]:
        saved = service.save_character_card(
            work["id"],
            {
                "expected_version": version(),
                "name": name,
                "source_type": "custom",
                "role": "核对公开记录",
                "voice_anchors": ["先核对再决定。"],
                "knowledge_boundary": "只知道公开档案",
                "ooc_constraints": ["不替别人决定"],
                "source_refs": ["合成验收设定"],
                "trust_status": "confirmed",
            },
        )
        cards.append(saved["card_id"])
    service.save_world_bible(
        work["id"],
        {
            "expected_version": version(),
            "title": "合成世界",
            "source_type": "custom",
            "entities": [
                {
                    "id": "world-archive",
                    "name": "档案室",
                    "kind": "place",
                    "summary": "白天可以进入",
                    "source": "合成验收设定",
                    "confidence_status": "confirmed",
                },
                {
                    "id": "world-garden",
                    "name": "庭院",
                    "kind": "place",
                    "summary": "开放场所",
                    "source": "合成验收设定",
                    "confidence_status": "confirmed",
                },
            ],
        },
    )
    chapter = service.get_work(work["id"])["chapters"][0]["id"]
    scenes = []
    for index, title in enumerate(["夜访档案室", "档案室的传闻（未选用）", "尚未检查的便条"]):
        saved = service.create_scene(
            work["id"],
            chapter,
            {
                "expected_version": version(),
                "title": title,
                "location": "本作场所",
                "goal": "核对房间出入记录",
            },
        )
        scene_id = saved["scene_id"]
        scenes.append(scene_id)
        service.configure_scene_context(
            work["id"],
            scene_id,
            {
                "expected_version": version(),
                "character_card_ids": [cards[1 if index == 1 else 0]],
                "world_item_ids": ["world-garden" if index == 1 else "world-archive"],
                "reference_file_ids": [],
            },
        )
        service.save_scene_manuscript(
            work["id"],
            scene_id,
            {
                "expected_version": version(),
                "expected_base_revision_id": None,
                "blocks": [
                    {
                        "id": "block-entry",
                        "type": "narration",
                        "text": "窗外的灯还亮着，档案员翻开当天的记录。她决定先核对登记，再决定是否打开房门。",
                    },
                    {
                        "id": "block-reply",
                        "type": "dialogue",
                        "speaker": "青禾" if index == 1 else "白露",
                        "text": "先核对记录吧。",
                    },
                ],
            },
        )
        if index < 2:
            service.review_scene(work["id"], scene_id, {"expected_version": version()})
    current = service.get_work(work["id"])
    artifact = next(
        a
        for a in current["artifacts"]
        if a["kind"] == "character_card" and a["scope_id"] == cards[0]
    )
    service.save_character_card(
        work["id"],
        {
            **artifact["current_revision"]["content"],
            "expected_version": version(),
            "card_id": cards[0],
            "knowledge_boundary": "不知道夜间口令",
        },
    )
    current = service.get_work(work["id"])
    bible = next(a for a in current["artifacts"] if a["kind"] == "world_bible")["current_revision"][
        "content"
    ]
    bible["entities"][0]["summary"] = "夜间进入需要双人核验"
    service.save_world_bible(work["id"], {**bible, "expected_version": version()})
    return {"work_id": work["id"], "card_ids": cards, "scene_ids": scenes, "chapter_id": chapter}
