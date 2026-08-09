# -*- coding: utf-8 -*-
"""
舞台引擎：管理立绘的站位、移动、进出场。

AA 的位置模型（由 137 个工程的数据反推确认）：
  - characters 数组的**下标就是该角色本行开始时所在的位置**（startingPos）
  - endingPos 是本行结束时移动到的位置；两者不等就是一次移动
  - 下一行该角色的下标 = 上一行的 endingPos
  - 位置 1~5 是立绘位，0 是"无立绘说话位"（旁白/只出声的角色）
  - 进出场靠 appear：3=登场 1=从左入 2=从右入 6=退场 4=向左退 5=向右退
    进出场的那一行 startingPos == endingPos

所以人物"活起来"靠的是：台上人数变化时重新排布，产生真实的走位。
"""

# 台上 N 人时的标准站位。中间优先，两侧对称。
LAYOUT = {
    0: [], 1: [3], 2: [2, 4], 3: [1, 3, 5],
    4: [1, 2, 4, 5], 5: [1, 2, 3, 4, 5],
}

APPEAR = {"": 3, "登场": 3, "a": 3,
          "右": 1, "从右": 1, "al": 1,
          "左": 2, "从左": 2, "ar": 2}
DISAPPEAR = {"": 6, "退场": 6, "d": 6,
             "左": 4, "向左": 4, "dl": 4,
             "右": 5, "向右": 5, "dr": 5}


class Stage:
    """一个场景内的舞台状态。"""

    def __init__(self, layout=None):
        self.layout = layout or LAYOUT
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

    # ---- 变更
    def leave(self, ident):
        self.pinned.pop(ident, None)
        return self.pos.pop(ident, None)

    def pin(self, ident, p):
        self.pinned[ident] = p

    def plan(self, order, hold=(), entering=()):
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

    def apply(self, target, entering=()):
        """落实站位。返回 {ident: (起点, 终点)}。
        entering 里的角色直接出现在终点，不产生移动。"""
        moves = {}
        for ident, dst in target.items():
            src = dst if ident in entering else self.pos.get(ident, dst)
            moves[ident] = (src, dst)
            self.pos[ident] = dst
        return moves
