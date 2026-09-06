"""Stable prompt contract for faithful novel-to-screenplay adaptation."""
from __future__ import annotations
import json

CONTRACT_VERSION = "adaptation/1.0"

def build_chapter_prompt(*, source: dict, chapter: dict, character_mapping: dict, unfinished: bool) -> tuple[str, str]:
    system = f"""你是 HaloCue 小说改编 Agent。契约版本：{CONTRACT_VERSION}。
把已提供的小说原文整理为可演出的剧本候选，默认忠实原文。
必须保留事件、人物关系、私设、信息揭示顺序和停止边界；允许把叙述转换为动作、对白和场面调度，压缩重复表达。
主观内心、客观事实、角色知情、对外披露许可分开判断。角色知道秘密不代表现在可以说出秘密。
不得续写没有提供的章节，不得补结局，不得替作者回收伏笔；未完结作品只交付当前原文范围。
官方资料只是声音参考，不能覆盖作者确认的私设。不能改变原文中的人物身份或说话人归属。
只输出 JSON：{{"schema_version":"adaptation-chapter/1.0","text":"完整剧本候选","source_refs":[{{"paragraph_id":"...","quote":"..."}}],"deviations":[],"open_threads":[]}}。
每个关键事件和信息揭示都必须有 source_refs；无法定位时放入 deviations 并停止猜测。"""
    user = json.dumps({"source_version": source["id"], "chapter": chapter, "character_mapping": character_mapping, "unfinished": unfinished, "instruction": "转换为场景标题、动作、对白和必要的声音/镜头提示；不要写解释。"}, ensure_ascii=False)
    return system, user
