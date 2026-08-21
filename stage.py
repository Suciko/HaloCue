# -*- coding: utf-8 -*-
"""
舞台引擎：管理立绘的站位、移动、进出场。

AA 的位置模型（由 137 个工程的数据反推确认）：
  - characters 数组的**下标就是该角色本行开始时所在的位置**（startingPos）
  - endingPos 是本行结束时移动到的位置；两者不等就是一次移动
  - 下一行该角色的下标 = 上一行的 endingPos
  - 位置 1~5 是立绘位，0 是"无立绘说话位"（旁白/只出声的角色）
  - 进出场靠 appear：3=淡入 1=从右入 2=从左入 6=退场 4=向左退 5=向右退
    进出场的那一行 startingPos == endingPos

所以人物"活起来"靠的是：台上人数变化时重新排布，产生真实的走位。
"""

import itertools

# 台上 N 人时的标准站位。中间优先，两侧对称。
LAYOUT = {
    0: [], 1: [3], 2: [1, 5], 3: [1, 3, 5],
    4: [1, 2, 4, 5], 5: [1, 2, 3, 4, 5],
}

APPEAR = {"": 3, "登场": 3, "a": 3,
          "右": 1, "从右": 1, "al": 1,
          "左": 2, "从左": 2, "ar": 2}
DISAPPEAR = {"": 6, "退场": 6, "d": 6,
             "左": 4, "向左": 4, "dl": 4,
             "右": 5, "向右": 5, "dr": 5}


DISTANCE_GAPS = {
    "intimate": 1,
    "approaching": 2,
    "normal": 4,
    "distant": 4,
    "remote": 4,
}


class Stage:
    """一个场景内的舞台状态。"""

    def __init__(self, layout=None, profiles=None, semantic_layout=True):
        self.layout = layout or LAYOUT
        self.profiles = profiles or {}
        self.semantic_layout = semantic_layout
        self.pos = {}            # ident -> 当前位置 1..5
        self.pinned = {}         # ident -> 用户显式钉死的位置
        self.auto = True         # 自动排布 / 手动站位

    # ---- 查询
    def on_stage(self):
        return list(self.pos)

    def at(self, ident):
        return self.pos.get(ident)

    def occupied(self):
        return set(self.pos.values())

    def free_slot(self, prefer=None):
        used = self.occupied()
        for p in ([prefer] if prefer else []) + [3, 2, 4, 1, 5]:
            if p and p not in used:
                return p
        return None

    def can_fit_composition(self, order):
        """Return whether known portrait footprints fit in one AA frame."""
        order = list(dict.fromkeys(order))
        if not order or len(order) > 5:
            return False
        return self._semantic_plan(order, (), (), {}) is not None

    # ---- 变更
    def leave(self, ident):
        self.pinned.pop(ident, None)
        return self.pos.pop(ident, None)

    def pin(self, ident, p):
        self.pinned[ident] = p

    def plan(self, order, hold=(), entering=(), intent=None):
        """算出目标站位。

        order     本行结束时台上角色的期望左右顺序，可以包含还没上台的。
        hold      这一行不许动的（正要退场的），钉在当前位置。
        entering  本行入场的。

        两条硬约束，违反了角色就会在 characters 数组里互相覆盖、凭空消失：
          1. 目标位置两两不同。
          2. **入场者的位置必须是当前空着的槽**。数组下标是 startingPos，
             入场者一出现就站在终点，若那个槽有人正要移走，两人下标会撞。
        """
        order = list(dict.fromkeys(order))
        if not order:
            return {}
        # Relationship distance is meaningful only for the two portraits that
        # are actually visible. Single shots stay centered; three-person shots
        # retain the stable 1/3/5 composition.
        intent = intent if isinstance(intent, dict) else {}
        has_portrait_geometry = any(self.profiles.get(ident) for ident in order)
        layout_intent = intent if len(order) == 2 else {}
        if (
            len(order) >= 2
            and self.semantic_layout
            and (layout_intent or has_portrait_geometry)
        ):
            enhanced = self._semantic_plan(order, hold, entering, layout_intent)
            if enhanced is not None:
                return enhanced
        return self._standard_plan(order, hold, entering)

    def _standard_plan(self, order, hold=(), entering=()):
        """Original deterministic layout, retained as the compatibility path."""
        entering, hold = set(entering), set(hold)
        occupied_now = set(self.pos.values())
        canon = self.layout.get(len(order), self.layout[5])

        target, taken = {}, set()

        def claim(i, p):
            target[i] = p
            taken.add(p)

        # 1. 钉死的：退场中的 + 用户显式指定的 + 手动模式下的全体
        for i in order:
            if i in target:
                continue
            p = None
            if i in hold and i in self.pos:
                p = self.pos[i]
            elif i in self.pinned:
                p = self.pinned[i]
            elif not self.auto and i in self.pos:
                p = self.pos[i]
            if p and p not in taken and not (i in entering and p in occupied_now):
                claim(i, p)

        # 2. 入场者：只能挑当前空着的槽。挑离自己在标准站位里那个名额最近的，
        #    平手取靠外侧的 —— 新人从边上进来比较自然。
        for i in [x for x in order if x in entering and x not in target]:
            k = order.index(i)
            want = canon[k] if k < len(canon) else 3
            free_now = [p for p in range(1, 6) if p not in taken and p not in occupied_now]
            if not free_now:
                continue                        # 装不下，交给调用方处理
            claim(i, min(free_now, key=lambda p: (abs(p - want), -p)))

        # 3. 台上原有的：保序配对，最小移动。
        #    按当前位置排好，目标槽也排好，一一对应 —— 这样谁都不用穿过谁，
        #    走位最短，也不会出现"先随便站下一行再全体重排"的来回倒腾。
        rest = sorted((i for i in order if i not in target),
                      key=lambda i: self.pos.get(i, 99))
        pool = [s for s in canon if s not in taken]          # 标准站位优先
        if len(pool) < len(rest):                            # 不够再补别的槽
            pool += [s for s in range(1, 6) if s not in taken and s not in pool]
        free = sorted(pool[:len(rest)])
        for i, p in zip(rest, free):
            claim(i, p)
        for i in rest[len(free):]:              # 实在没槽了，原地不动
            if i in self.pos and self.pos[i] not in taken:
                claim(i, self.pos[i])

        assert len(set(target.values())) == len(target), "目标站位撞了"
        starts = [target[i] if i in entering else self.pos.get(i, target[i])
                  for i in target]
        assert len(set(starts)) == len(starts), "起始位置撞了"
        return target

    def _semantic_plan(self, order, hold, entering, intent):
        """Pick the best legal AA layout for semantic staging intent.

        Slot safety and authored positions remain hard constraints. Narrative
        distance, portrait geometry and continuity are soft scoring goals, so
        unusual shots remain possible without making one phrase a rigid map.
        """
        entering, hold = set(entering), set(hold)
        occupied_now = set(self.pos.values())
        pinned = {}
        for ident in order:
            if ident in hold and ident in self.pos:
                pinned[ident] = self.pos[ident]
            elif ident in self.pinned:
                pinned[ident] = self.pinned[ident]
            elif not self.auto and ident in self.pos:
                pinned[ident] = self.pos[ident]

        if len(set(pinned.values())) != len(pinned):
            return None

        candidates = []
        for slots in itertools.permutations(range(1, 6), len(order)):
            target = dict(zip(order, slots))
            if any(target[ident] != slot for ident, slot in pinned.items()):
                continue
            if any(target[ident] in occupied_now for ident in entering):
                continue
            if not self._portrait_spacing_is_safe(order, target):
                continue
            starts = {
                ident: target[ident] if ident in entering else self.pos.get(ident, target[ident])
                for ident in order
            }
            if not self._portrait_spacing_is_safe(order, starts):
                continue
            candidates.append((self._layout_score(order, target, intent), target))
        if not candidates:
            return None

        _, target = min(candidates, key=lambda item: item[0])
        starts = [target[i] if i in entering else self.pos.get(i, target[i]) for i in order]
        assert len(set(target.values())) == len(target), "目标站位撞了"
        assert len(set(starts)) == len(starts), "起始位置撞了"
        return target

    def _portrait_spacing_is_safe(self, order, target):
        """Reject layouts whose known portrait footprints would overlap."""
        for left_index, first in enumerate(order):
            for second in order[left_index + 1:]:
                first_slot, second_slot = target[first], target[second]
                if first_slot <= second_slot:
                    left, right = first, second
                else:
                    left, right = second, first
                left_profile = self.profiles.get(left) or {}
                right_profile = self.profiles.get(right) or {}
                required = max(
                    self._positive_int(left_profile.get("min_slot_gap"), 1),
                    self._positive_int(right_profile.get("min_slot_gap"), 1),
                )
                if abs(first_slot - second_slot) < required:
                    return False
        return True

    @staticmethod
    def _positive_int(value, default):
        try:
            return max(default, int(value))
        except (TypeError, ValueError):
            return default

    def _layout_score(self, order, target, intent):
        canon = self.layout.get(len(order), self.layout[5])
        focus = intent.get("focus_character")
        reaction = intent.get("reaction_target")
        pair = []
        for ident in (focus, reaction):
            if ident in order and ident not in pair:
                pair.append(ident)
        if len(pair) < 2 and len(order) == 2:
            pair = list(order)
        elif len(pair) == 1:
            nearest = min(
                (ident for ident in order if ident != pair[0]),
                key=lambda ident: abs(target[ident] - target[pair[0]]),
                default=None,
            )
            if nearest:
                pair.append(nearest)

        score = 0
        referenced = {
            ident for ident in (focus, reaction) if ident
        }
        desired_gap = (
            DISTANCE_GAPS.get(str(intent.get("relation_distance") or ""))
            if not referenced or referenced <= set(order)
            else None
        )
        if desired_gap and len(pair) == 2:
            score += abs(abs(target[pair[0]] - target[pair[1]]) - desired_gap) * 30

        # The normal symmetric layout is a preference, not a fixed answer.
        score += sum(abs(target[ident] - canon[index]) * 2 for index, ident in enumerate(order))

        movers = 0
        movement = 0
        for ident in order:
            if ident in self.pos:
                delta = abs(target[ident] - self.pos[ident])
                movement += delta
                movers += int(delta > 0)
        score += movers * 7 + movement * 4

        inversions = 0
        for left_index, left in enumerate(order):
            for right in order[left_index + 1:]:
                if target[left] > target[right]:
                    inversions += 1
                if left in self.pos and right in self.pos:
                    before = self.pos[left] - self.pos[right]
                    after = target[left] - target[right]
                    if before and after and (before < 0) != (after < 0):
                        score += 16
        score += inversions * 5

        for ident in order:
            slot = target[ident]
            profile = self.profiles.get(ident) or {}
            direction = profile.get("face_direction")
            if direction == "left":
                score += max(0, 3 - slot) * 5 + abs(slot - 4)
            elif direction == "right":
                score += max(0, slot - 3) * 5 + abs(slot - 2)
            if profile.get("has_weapon") or profile.get("has_wings"):
                score += min(abs(slot - 1), abs(slot - 5)) * 3
            if ident == focus:
                score += abs(slot - 3)

        for left_index, left in enumerate(order):
            for right in order[left_index + 1:]:
                if abs(target[left] - target[right]) != 1:
                    continue
                left_profile = self.profiles.get(left) or {}
                right_profile = self.profiles.get(right) or {}
                if (
                    left_profile.get("framing") == "closeup"
                    or right_profile.get("framing") == "closeup"
                    or left_profile.get("has_weapon")
                    or right_profile.get("has_weapon")
                    or left_profile.get("has_wings")
                    or right_profile.get("has_wings")
                ):
                    score += 8

        slots = tuple(target[ident] for ident in order)
        return score, movers, movement, inversions, slots

    def apply(self, target, entering=()):
        """落实站位。返回 {ident: (起点, 终点)}。
        entering 里的角色直接出现在终点，不产生移动。"""
        moves = {}
        for ident, dst in target.items():
            src = dst if ident in entering else self.pos.get(ident, dst)
            moves[ident] = (src, dst)
            self.pos[ident] = dst
        return moves
