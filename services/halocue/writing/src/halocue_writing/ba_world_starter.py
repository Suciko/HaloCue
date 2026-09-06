from __future__ import annotations

"""A deliberately unverified starting structure for BA fan-work settings.

This is a product template, not an excerpt from the official corpus.  It gives
each Work a small, editable vocabulary to begin with while keeping the user in
control of what becomes confirmed world knowledge.
"""

BA_WORLD_STARTER_VERSION = "ba-world-starter/1.1.0"
BA_WORLD_STARTER_SOURCE = "HaloCue BA 世界观起始架构 1.1（待原作资料核对）"


def starter_entities() -> list[dict]:
    return [
        {
            "id": "ba-starter-kivotos",
            "name": "基沃托斯",
            "kind": "place",
            "summary": "多所学院共存的学园都市。本作应继续用已登记的原作摘录或用户决定，明确这次故事实际涉及的区域与限制。",
            "aliases": [],
        },
        {
            "id": "ba-starter-schale",
            "name": "夏莱",
            "kind": "organization",
            "summary": "面向基沃托斯事务的组织框架。请在本作中明确它是否出场、拥有何种权限，以及角色已知到什么程度。",
            "aliases": [],
        },
        {
            "id": "ba-starter-general-student-council",
            "name": "联邦学生会",
            "kind": "organization",
            "summary": "跨学院事务的设定入口。需要时再补充本作采用的职责、信息边界与证据来源。",
            "aliases": [],
        },
        {
            "id": "ba-starter-academy-network",
            "name": "学院自治结构",
            "kind": "academy",
            "summary": "各学院及其社团可以作为故事发生的具体单位。请新建或补充当前作品真正涉及的学院、社团与场所。",
            "aliases": [],
        },
        {
            "id": "ba-starter-halo",
            "name": "学生光环",
            "kind": "technology",
            "summary": "作为角色外观、伤害表现与身份认知的设定入口。请在本作中明确是否涉及、角色如何理解它，以及任何原创改写的边界。",
            "aliases": [],
        },
        {
            "id": "ba-starter-clubs",
            "name": "社团与部活动",
            "kind": "organization",
            "summary": "把具体社团、部门或兴趣小组登记成独立卡片前的共同入口。请补充本作涉及的成员、活动地点、权限和冲突。",
            "aliases": [],
        },
        {
            "id": "ba-starter-abydos",
            "name": "阿拜多斯高中",
            "kind": "academy",
            "summary": "可作为原作参考或本作改写的学院入口。请补充本作实际采用的地点、成员、时间点和证据，未核对前不作为写作事实。",
            "aliases": [],
        },
        {
            "id": "ba-starter-millennium",
            "name": "千年科学学园",
            "kind": "academy",
            "summary": "可作为技术、研究与社团故事的学院入口。请仅登记本作真正采用的组织、人物关系和技术限制。",
            "aliases": [],
        },
        {
            "id": "ba-starter-trinity",
            "name": "圣三一综合学园",
            "kind": "academy",
            "summary": "可作为学院、宗教氛围与社团关系的学院入口。请为本作补齐具体场所、关系边界和来源。",
            "aliases": [],
        },
        {
            "id": "ba-starter-gehenna",
            "name": "格黑娜学园",
            "kind": "academy",
            "summary": "可作为学院、社团与日常冲突的学院入口。请确认本作采用的版本，避免让模糊印象直接进入正文。",
            "aliases": [],
        },
        {
            "id": "ba-starter-hyakkiyako",
            "name": "百鬼夜行联合学院",
            "kind": "academy",
            "summary": "可作为传统、庆典与不同社团关系的学院入口。请把本作实际使用的地点和时间线独立登记。",
            "aliases": [],
        },
        {
            "id": "ba-starter-red-winter",
            "name": "红冬联邦学园",
            "kind": "academy",
            "summary": "可作为学院组织与日常生活的学院入口。请用已登记资料或用户决定确认本作采用范围。",
            "aliases": [],
        },
    ]


def starter_bible() -> dict:
    return {
        "title": "BA 世界观与本作设定",
        "source_type": "ba_starter",
        "entities": [
            {
                **entity,
                "source": BA_WORLD_STARTER_SOURCE,
                "source_type": "ba_starter",
                "confidence_status": "open",
                "scope": "work",
                "participants": [],
                "status": "active",
            }
            for entity in starter_entities()
        ],
        "rules": [],
        "timeline": [],
    }
