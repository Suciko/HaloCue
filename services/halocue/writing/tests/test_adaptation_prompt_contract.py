from halocue_writing.adaptation_prompts import build_chapter_prompt


def test_prompt_keeps_unfinished_and_information_boundary_explicit():
    system, user = build_chapter_prompt(
        source={"id": "source-1"},
        chapter={"id": "chapter-1", "title": "第一章", "paragraphs": [{"id": "p-1", "text": "她知道门后的秘密。"}]},
        character_mapping={"她": "character-a"},
        unfinished=True,
    )
    assert "不得续写没有提供的章节" in system
    assert "角色知道秘密不代表现在可以说出秘密" in system
    assert "source_refs" in system and "adaptation-chapter/1.0" in system
    assert '"unfinished": true' in user
