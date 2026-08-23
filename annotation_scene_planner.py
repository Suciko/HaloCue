"""Dialogue-only event planning for the annotation director.

This pass sees no official command stream and chooses no AA asset.  It gives
later chunk calls a scene-wide event spine so they do not reduce a sequence to
independent speaker turns.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping, Sequence
from typing import Any


EVENT_KINDS = (
    "arrival", "disturbance", "group_escalation", "reveal", "discovery",
    "object_test", "inference", "invitation", "decision", "montage",
    "aftermath", "dialogue_cluster",
)
EVENT_PHASES = (
    "cue", "reveal", "group_reaction", "focus_handoff", "action",
    "object_action", "feedback", "verification", "result", "decision_pause", "time_bridge",
    "aftershock", "relay",
)
# A few gateways have returned the event kind as a phase.  Keep this one
# documented compatibility spelling at the wire boundary, then normalize it
# back to the actual execution phase and audit the repair.  Do not broaden this
# into accepting arbitrary phase guesses.
PHASE_COMPAT_ALIASES = {
    "object_test": "object_action",
}
PHASE_SCHEMA_VALUES = tuple(dict.fromkeys((*EVENT_PHASES, *PHASE_COMPAT_ALIASES)))
PEAK_TYPES = ("solo_emphasis", "relationship_peak", "group_reaction")
SHOT_OPERATIONS = (
    "establish", "hold", "reframe", "expand", "shrink", "switch",
    "anchor_match_cut",
)
FRAMING_INTENTS = ("wide", "medium", "medium_close", "close", "relation", "group")
PERFORMANCE_CARRIERS = (
    "face_change", "emoticon", "action", "sound", "camera_change",
    "movement", "entry_exit", "background_change", "pose_hold",
)

_PHASE_BEAT_REASONS = {
    "cue": {"offscreen_cue"},
    # A reveal may be an arrival, but discovery/recognition beats are often
    # carried by an object operation or a listener's physical reaction.
    "reveal": {"entrance_reveal", "object_operation", "listener_reaction", "physical_reaction"},
    "group_reaction": {"group_reaction"},
    "focus_handoff": {"listener_reaction"},
    "action": {"physical_reaction", "object_operation"},
    "object_action": {"object_operation"},
    "feedback": {"object_operation", "physical_reaction", "listener_reaction"},
    "verification": {"object_operation", "physical_reaction", "listener_reaction"},
    "result": {"object_operation", "listener_reaction", "physical_reaction"},
    "decision_pause": {"decision_pause", "await_response"},
    "time_bridge": {"montage"},
    "aftershock": {"exit_aftershock", "listener_reaction", "comedy_hold", "decision_pause"},
    "relay": {"listener_reaction"},
}


PLANNER_SYSTEM = """你是视觉小说演出的场景事件规划器。你只会看到盲测台词，不会看到官方演出答案，
也不选择具体 face_id、气泡、动作、背景或音效。你的任务是先把整场戏切成少量连续事件单元，让后续导演
先按事件因果理解剧情，再自由选择关系镜头或正反打。单人正反打是正常且常用的镜头语法，不能预设禁止。

先按下面的顺序完成整场规划，再填写 Schema；这是分析顺序，不是不可推翻的答案。后面的证据可以修正前面的假设：
1. 先找事件边界、stimulus、stimulus_targets 和 outcome，建立因果与互动轴。
2. 再按互动轴建立有起止范围的 shot_groups；先确定连续镜头覆盖范围，不能从逐句 speaker 反推镜头。
3. 再按时间顺序比较每个关键人物“上一有效演出节点（对白或无对白）→当前拍”的状态变化，判断 peaks、release、
   face_arcs 以及确有必要的 silent_beats。情绪变化不能只写在抽象 outcome 里而不留下可执行锚点。
4. 最后为已经确定的情绪阶段写 face_arcs，为已有演出目的写最少但完整的 performance_intents；每个阶段变化都要说明
   change_reason，并至少落到 face_change、emoticon、action、camera_change、movement、entry_exit 或 sound 之一。
5. 输出前核对：每个计划字段都有台词证据，必要事件链没有被后加的微节拍挤掉；不要为了填满 Schema 增加内容。

每个事件先找 stimulus、直接受影响的 stimulus_targets 和 outcome，再安排 phase_order。明确 result_owner、
aftershock_owner 和 release_owner；没有对应阶段时留空，不能把当前镜头全员自动当成结果承受者。stimulus_targets
表示“可能被事件触及的人”，不等于他们必须同步反应；group_reaction 的 participants 只能来自这组人，
aftershock 可以只交给其中一个结果承受者，或交给后续才被刺激到的观察者。shot_groups 是连续镜头区间，
anchor_i 表示这幅构图开始生效，hold_until_i 表示首选的连续镜头范围；只有确实选择持镜后才保持该区间。
如果互动轴、结果承受者、揭晓、峰值或关系压力在区间中明确改变，可以直接建立带理由的完整硬切，不要为了满足 hold_until 继续挂住旧构图。
只有拍摄小组、焦点、景别意图或互动轴真正变化时才建立下一个区间，不把 shot_groups 写成逐句镜头表。每组最多三人，
不是房间里所有在场者，也不是把每位说话者自动与被谈论对象组成双人。共同刺激确实同时作用于多人时，
才规划 group_reaction；如果台词只支持先后接力，就用 focus_handoff/relay，不要因为 stimulus_targets 有多人
就补一个同步拍。互动轴、承受者、揭晓或爆点改变时可以硬切；
同一问答、同一操作或同一笑点仍在推进时可以持镜，也可以在问者与答者之间做有目的的单人正反打；
不能把同一问答自动等同于同框。受话者或被谈论者不必留在当前镜头，回答者说话时也不必把提问者挂在旁边。
如果当前镜头已有稳定的关系组，而第三人只是旁观、沉默、用省略号或短反应逐步进入，先把他当作
同一事件中的观察者：保留原关系组和原有槽位，必要时让观察者从空槽 reveal 或在画外承接；不要因为
观察者出现/说话就强行把原关系组改成居中单人或重新洗牌。只有观察者成为新的互动轴、关系压力承受者
或结果所有者时，才建立新的 shot_group。规划时同时检查“谁被看见”和“谁正在承受刺激”，两者可以不同。
被追问后的检查结果、调查结果、计划说明或正式确认，要额外判断它是“关系中的来回确认”，还是汇报者第一次
完整交代新事实的独立信息落点。前者可以持双人，后者可以先切汇报者单人，等确认/追问/情绪余波再回关系镜头；
不要把“有人提问”当成汇报句必须持续双人同框的理由，也不要把这个模式套到所有普通补充句。
多人连续向同一人追问、确认或评价时，先判断每句的视觉承受者：可以完整硬切轮换关系伙伴，也可以切成各自单人；
只有必须同时看见关系压力或共同反应时才保留关系镜头。有动机的完整硬切搭档轮换是合法镜头语法，
可以让话题锚点保持同一侧；禁止的是把这种完整换组写成 hold/reframe，让另一侧人物无过程弹现或让锚点来回滑动。

arrival 只有在正文给出真实到场证据时才使用；有证据时可以由对白节点上的 enter/reveal 或独立静默拍承载，
不因为“第一次露面”自动增加静默节点。原本就在房间、只是第一次被镜头拍到的人属于显现或普通建立镜头。
稍后的欢迎、来处或刚到确认可以补充到场证据，也可以把这种后文证据归回人物首次出现的拍点，但不能把某种固定镜头顺序当成硬模板。
object_test 只有在正文确实描述试机、操作或结果验证时才使用；当台词显示角色还要等待反馈、怀疑是否生效或重复确认时，可以在两者之间规划
feedback / verification 微节拍，没有证据时不要补齐。decision_pause 只有在正文存在可读犹豫、等待回应或决定停顿时才规划；
“decision”事件本身不自动要求静默拍。montage 只有在文本存在时间跳跃或持续活动确实无法逐句展示时才规划 time_bridge；
否则不要凭“活动”这个事件类型补蒙太奇，并用不同功能的过程变化连接开始与结果。

peak 必须区分三类：solo_emphasis 是个人爆发或关键细节，relationship_peak 是两人关系变化，group_reaction 是多人共同承受刺激。
peak 表示场景内的相对升级或结构转折，不等于音量大、感叹号或积极语气。同一升级链比较 setup 与 payoff，
把最能改变画面功能的一拍作为峰值；建立、说明和释放拍不要重复标峰值。
只有 solo_emphasis 才要求单人 close 构图；另外两类保留关系或共同反应。第一阶段只写 visual_intent 和 carriers，
禁止直接指定 FocusLine、集中线、jump、hophop 等具体 AA 资源。没有真正峰值的事件可以让 peaks 为空，不按数量制造爆点。
个人高声宣告、找回关键物后的尖叫、连续强句后一句的升级和单人态度转折，都要优先判断是否为 solo_emphasis；
只有听者同时承担关系变化或同一刺激时才改为 relationship_peak / group_reaction，不能因上一镜已有多人而省略判断。
但一旦已经判断为 solo_emphasis，就不能只写一个近景镜头而把表演层全部留空：同一锚点的 performance_intents
至少要求 face_change / emoticon / action 之一，第二阶段再从合法资源中选择语义相符的实现。克制是避免误用，
不是把特写、集中线、气泡和动作一律清零；正文有明确峰值时必须让观众看得出它与普通对白的差别。
同一升级链的 peak 要写 release；可释放到后续行、next_event 或 scene_end。
峰值若回答了担忧、质疑或提议，检查正文是否支持非说话者的结果反应；有证据时放在峰值后的
aftershock / focus_handoff，不能用峰值之前的停顿冒充结果余波。

silent_beats 只规划有可读目的的无对话框节点，例如画外声源、共同反应、发现后的确认、操作反馈、决定前沉默
或活动时间跳跃。每个 silent_beat 都必须有可见或可听的新信息，不能用空等待代替事件，也不能把普通对白节点写成 wait。
如果某个角色在上一拍与下一句之间必须先完成一个有意义的表情/动作反应，且把它塞进下一句会让反应因果消失，
应把它保留为独立 silent_beat；如果下一句可以自然承载该变化，就不要为了增加节点另造静默拍。
phase 名称只是描述当前文本已经存在的功能，不是待补齐清单。物件试机、邀请/接受、持续活动都先逐句判断哪些
状态变化已经由对白本身表达，哪些信息确实需要脱离对话框单独展示；只规划后者。不得因为事件被命名为
object_test、invitation、decision 或 montage，就自动补接触、反馈、验证、停顿、软化、余波或时间桥。
连续评价同一对象时，根据当前承受关系选择单人、双人或画外评价，不预设固定接力形式。

听觉载体单独过证据门：只有正文明确出现可听见的声源、启动反馈、机械声、警报、脚步或其他可靠听觉结果时，
才把 sound 放进 carriers；“开始操作”“确认成功”本身不等于有声音。没有独立听觉事实时不要把 sound 写进
require_all=true，也不要为了让 G2 看起来更完整而补音效。若声音只是多个等价表达中的一种，可以保留 sound
作为可选 carrier，但 G2 应按当前可用资源和语义选择，不因计划中出现它就强制添加。

phase_order 可使用 cue / reveal / group_reaction / focus_handoff / action / object_action / feedback / verification / result /
decision_pause / time_bridge / aftershock / relay。silent_beats 只列真正没有对话框但第二阶段必须兑现的 phase：
画外 cue 必须有声音或其他明确载体；同步 group_reaction 把反应者放在同一拍。若 A 的反应成为 B 的新刺激，
则在同一关系/三人镜头用 action -> relay -> aftershock 交接所有权，不压成全员同拍，也不逐人切镜。object_action 必须产生
接触或启动动作；feedback / verification 必须各自提供新的可读状态，不能只复制同一张脸和同一个动作；decision_pause 必须有停顿承接；time_bridge 必须用声画变化连接活动前后，不能只是空等。
relay 通常由对白镜头完成；只有前一无对话框反应成为下一人的刺激时才用 silent relay，不为普通评价强造静默拍。

每个 silent_beat 都要写 carrier_requirement。普通反应拍至少需要 face_change、emoticon、action、camera_change、movement、
entry_exit、sound 或 background_change 之一；只有有明确目的的 decision_pause 可以使用 pose_hold + Wait。face_arcs 只描述
角色的语义阶段和变化原因，不写 face 编号。只要同一角色在事件中出现可见的态度、潜台词、注意对象、强度或
反应阶段变化，face_arcs 就必须列出变化前后的阶段；每个后续变化点还要为该角色规划 face_change、emoticon、
action 中至少一种可读表演。优先换成语义相符且视觉有差异的脸；若没有合适的新脸，允许保持当前脸并用气泡或
动作承载变化，不能为了换编号选语义更差的表情。performance_intents.carriers 只表示同一 primary phenomenon 的可替代实现集合，
这不是只挑高潮：疑问→确认、惊讶→掩饰、汇报→放松、争执→余波等短阶段也要按相邻演出节点逐一比较；同一短反应
拍可以 hold，但不能让笼统的“同一情绪”掩盖已经发生的阶段变化。
第二阶段在指定 anchor、position 和 subjects 上兑现同一现象的一种载体即可；不同现象不能用 face 替代。只有物件操作、入退场或声画共同构成因果、
缺少任一层都会改变事实时才写 require_all=true，要求全部兑现。若同一锚点有两个独立且有正文证据的现象，应拆成两个 intent，或明确使用 require_all=true；不要把仅仅“可以考虑”的动作或气泡列进去。
留给第二阶段的 face 空串只会继承旧脸，不能兑现阶段变化。group_escalation、discovery、
inference、invitation、decision、aftermath 这类本身依赖人物反应的事件，至少要规划一个 face_change、emoticon
或 action 表演意图；这按剧情事件判断，不按固定次数凑数量。performance_intents 只描述需要由哪些表演层承载，
不写具体资源名。问号、感叹号、省略号、破折号等强标点只是必须复核的信号，不是自动映射气泡或动作的规则；
结合相邻台词判断疑问、惊讶、迟疑、自我修正、汇报、补充、确认和情绪释放是否形成新的表演阶段。汇报或确认
若真的承担了从担忧到稳定、从未知到已知的转折，可规划 face_change / emoticon / action 作为可替代载体；不要
因为出现“报告”二字就机械指定动作或气泡。

表演层要按强度和身体状态组合，而不是把情绪词一对一映射资源：压住火气可以由愤怒 face + 怒筋 + stiff
承载，较轻、较短的情绪重音可以由怒筋 + jump 承载，更重并需要连续多跳的情感才考虑 hophop，明显失控/挣扎才考虑 shake；害羞或被戳穿
可以是羞涩 face、脸红/冷汗和 stiff 的一个或多个组合，轻微难为情不必堆满，`fire` 若是燃烧音效只能跟真实
燃烧事件。这里写的是可替代 carriers 和阶段原因，不是固定配方，也不要求每句都出现资源。
强度要和正文证据、人物基线及相邻阶段的增量相称。一个事件中的相对峰值仍可能只是克制的安心、忧虑或迟疑；
单人承受情绪也不自动需要 close / medium_close。只有观众确实需要看清细节、关系距离或个人爆发时才规划近景，
否则保持 medium 或关系构图，把阶段变化交给最自然的 face / emoticon / action 中一项即可。不得因为“这里是转折”
就同时升级近景、哭泣符号和动作；每一层都要能分别指出正文依据。

新增 feedback / verification 等微节拍是在已有事件骨架上细化因果，不是数量交换：不能因此删除其他有正文证据的
入场、共同反应、焦点交接、峰值表演或余波。先保留全场必要事件，再局部细化；没有正文证据的阶段仍然不要补。

多人事件先区分“即时反应者”和“最终承受结果的人”：前者可以同步，也可以按 relay 接力；后者不必是
前者全体。aftershock 只在正文给出持续影响、无奈收束或观察者补刀时规划，并把镜头交给真正承受那一拍
的人。不能把事件的全部 stimulus_targets、当前镜头全员或所有说话者自动当成 group_reaction participants，
也不能因为有多人反应就强制添加第三人。

不要复制输入台词，不解释推理，不按固定数量制造事件。只输出符合 Schema 的 JSON。"""


LEGACY_PLANNER_SYSTEM = PLANNER_SYSTEM


PLANNER_SYSTEM_COMPACT = """你是视觉小说演出的场景事件规划器。你只看盲测台词，不看官方命令流、人工标注或旧模型结果，
也不选择具体 face_id、气泡、动作、背景、音效或槽位。你的产物是给 G2 的语义假设，不是官方答案。

官方样本只能提供导演语法，不能提供当前文本的节奏模板；当前输入文本及其上下文是唯一剧情证据。演出推断采取主动标准：
听者停顿、视线变化、克制的身体反应或有动机的反打，只要是当前因果和人物关系的自然结果，就可以规划，即使原文没有
括号动作。剧情事实采取严格标准：不能凭空增加物件操作、人物到场/离场、事件结果、新关系事实或时间流逝；这些都需要正文证据。

## 唯一分析顺序
这是分析顺序，不是不可推翻的答案：
1. 按因果而不是按 speaker 切少量连续事件，写 start_i/end_i、stimulus、真正被直接触及的 stimulus_targets 和 outcome。
2. 只有正文明确或强因果支持时才写 phase_order、result_owner、aftershock_owner、release_owner；多人触及不等于他们必须同步反应，
   先后接力也可以是不同所有权。上一有效演出节点（对白或无对白）只作为阶段比较的上下文。
3. 只有确有必要时才写 shot_groups、focus_turns、silent_beats、face_arcs、performance_intents 或 peaks。
   独立 silent_beat 必须有新的可见/可听目的；有台词的节点不规划 Wait。事件类型不会自动补蒙太奇、反馈、验证或决定停顿。

角色表会把人物分成 DISPLAYABLE_CAST 与 OFFSCREEN_NAMED_SPEAKERS。DISPLAYABLE_CAST 只表示“有可用立绘资源”，
不表示人物在场、已经入镜或应该从场景开头出现。后者是“有姓名的画外发言者”：可以拥有台词、
参与 stimulus/outcome/关系语义，也可以成为被画面中角色注视或回应的对象；但他们没有立绘，绝不能进入 shot_groups.members、
focus_turns、face_arcs、performance_intents.subjects、silent_beats.participants 或 peaks.subject。涉及他们的关系变化，要把可见反应
规划给 DISPLAYABLE_CAST 中真正能演出的人；有立绘说话者的刺激若与对白同拍落地且反应不必先于下一句独立展示，
把该可见承受者标成 listener reaction 的执行对象，供 G2 用行级 `reactions` 承载。画外/旁白说话者不自动触发同拍反应；
只有正文明确写出画内角色响应画外声音时，才规划独立 silent_beat。不能为了双人关系构图虚构其立绘、站位、入退场、表情或动作。

## 积极演出扫描（唯一版本）
每个事件都主动检查六类机会：注意对象改变；预期被打破或新信息落地；回答前的犹豫或压住情绪；可见身体意图；
关系压力或距离改变；结果落地后的情绪余波。有因果价值时，默认让变化可读，不等待原文逐字写出舞台指示。

先判断变化能否自然承载在对白节点；可以时规划 face_change、emoticon、action、camera_change、movement、entry_exit 或 sound
中最具体、最能让因果与人物状态可读的一项或少数组合。有立绘说话者同拍击中可见听者时，保留该 listener reaction，
让 G2 在行级 `reactions` 中明确承受者；画外/旁白说话者不自动产生该字段。只有画内反应或结果必须在下一句开口前被观众单独读到、
且正文有证据时，才规划 silent_beat。
多个机会并存时选择最能增加因果可读性的一项或少数几项，不设节点、镜头或资源配额；普通信息交换没有阶段变化时可以自然保持。

表情阶段要按“同一角色上一次真正可见的发言或表演”比较，不按紧邻台词的说话人比较。再次开口时，若语用从追问变成
辩解、从强装镇定变成被注视后的不自在、从说明变成短促命令，即使大类情绪相近，也应写成更细的 face_arc 阶段；
不能把整段压成一个“惊讶”或“生气”。自定义表情库中的近义脸常用于同一情绪内部的语气推进，规划时保留这些细分机会；
官方表情较少时才更常自然保持。保持同一脸必须表示同一具体态度仍在持续，而不是因为省略最安全。

气泡先看语用和人物基线，再看标点：问号与感叹并存且预期被打破时可规划惊疑；普通追问偏疑问；突然注意到刺激、
被叫住或快速接住上一拍可规划 respond/反应；强烈羞恼、气急或冒火式抗议可规划 steam/冒烟。极端惊讶是低频强反应，
省略号、问句或音量本身不能证明它。若身体动作与瞬时心理同时可读，action 与 emoticon 是两个独立机会。

先决定这一拍要让观众读到什么身体、注意力或关系变化，再决定用哪一层承载；不能从“哪个字段最容易省略”倒推演出。
身体反应本身若是这一拍的新信息，就为它单独规划 action intent，不能和 face_change 塞成可随意舍弃的二选一。

主动抵抗最低工作量偏置：省略、hold 和 face-only 不是天然安全答案，而是必须有正面导演理由的选择，例如有意的聆听、
压抑、静止或信息确实未变化。决定它们之前，先比较一个更具身体、关系或镜头表达的合法方案；若该方案有因果依据且让人物
更可读，就应规划它。合理的演出不会因为指令较多受罚，低指令数量不等于克制或质量；这也不构成任何资源数量配额。

语义例子：新事实击中听者，可先让听者读到反应再回答；人物嘴硬但关系压力已改变，可让视线、表情或克制动作承载潜台词；
操作结果决定下一句意义时，可先呈现反馈；纯信息交换没有反应阶段变化时保持即可。这些例子说明判断方向，不绑定资源组合。

## 软导演先验
`shot_groups.members` 是该组 anchor 时刻观众实际看见的立绘，不是整个事件的 participants，也不是之后会说话的人物名单。
场景开头或新事件开始时，先根据截至 anchor 的正文与当前跨段状态判断谁已经可见；不能因为演员表里有某人、后文轮到某人说话、
或某人属于 stimulus_targets，就把他提前摆进更早镜头。后文人物可以在其对白、被明确看见/点到、reveal、真实 enter，或有依据的完整
cut 时加入；若上下文已明确多人共同在场，则允许他们在开口前进入关系镜头。这里约束的是可见性事实，不限制有依据的关系构图。

单人正反打是正常且常用的镜头语法；受话者或被谈论者不必留在当前镜头，不能把同一问答自动等同于同框。
有动机的完整硬切搭档轮换是合法镜头语法，角色可以跨 hard cut 保留同一侧；不要把换组写成 hold/reframe 或无过程换图层。
同一问题尚未解决时，可以让真正的因果锚点保持原槽位，另一侧按接力需要更换角色。锚点应是被讨论对象、信息持有者、
直接承受者或下一拍仍有作用的人，而不是为了少移动随机留下的人。若被换下者之后没有连续专门拍点，这种同位换人
可以比先切其单人、再切下一人更顺；若双方都需要连续独立承接，则使用有动机的完整反打，避免短促的一句一切。
镜头组最多三人，关系镜头服务互动轴而不是房间全员。只有观察者成为新的承受者或互动轴时才加入。
如果问题尚未得到回答，信息持有者或直接受影响者仍可作为因果锚点；旁支人物对措辞的短暂纠正不必自动取代未决的问答轴。
独立信息落点可以先切汇报者单人，再在确认或余波时回关系镜头；不要把这个模式套到所有普通补充句。
说话人变化本身不是新镜头理由；同一刺激和互动轴仍在推进时，优先保留关系组或连续镜头，只有承受者、关系压力、
揭晓、峰值或互动组真正改变时才规划新的 shot_group。

## 三条可选事件路径
同一对象或主张仍在来回确认时，优先把它规划为一个关系事件，让焦点在组内承接；不要按 speaker 逐句拆组。
发现、操作、反馈、验证或余波只有在观众需要于下一句前读到独立反应或新事实时才拆成 silent_beat，并写出对应阶段与最小载体要求。
明确的个人爆点可以规划 solo peak，再写 release 回听者或关系组；peak 不是感叹号配额，也不是每个事件都要有。

## 表演与静默判断
peak 只表示场景内的相对升级，不是感叹号配额；先比较 setup/payoff，再决定是否 solo_emphasis、relationship_peak 或 group_reaction。
强标点只是必须复核的信号，不是机械指定动作或气泡。疑问→确认、惊讶→掩饰、汇报→稳定等阶段只有在正文有变化时
才写 face_arc 或 performance_intent。carrier 的“默认表示可替代的实现集合”，只适用于确实能等价表达同一现象的载体，
不是数量交换；只有 `require_all=true`
才要求全部。需要表演时至少说明 face_change、emoticon、action、camera_change、movement、entry_exit 或 sound 之一，
但不按固定次数凑数量；压住火气、害羞或被戳穿只是语义例子，不是关键词触发器。
连续阶段可以共用一个持续的身体意图；只有新出现的身体信息才把 action 列为载体。`require_all=true` 只表达正文已证明的
组合事实，例如可见操作与独立可听反馈共同构成结果；情绪强、个人峰值或“更有演出感”本身不需要多个载体同时兑现。
强度按正文证据、人物基线和相邻阶段增量判断；相对峰值仍可能只是克制的安心、忧虑或迟疑。单人承受情绪也不自动需要 close，
只有必须看清细节、关系距离或个人爆发时才规划近景；不要因为“这里是转折”就同时升级近景、哭泣符号和动作，
每一层都要能分别指出正文依据。
从多人镜头收成其中一人的单人镜头时，先检查新画面是否真的可读：只删除同伴、保留者仍是同尺度普通中景，
观众只会看到人物突然消失。此时优先继续关系镜头或使用因果锚点接力；确实需要独立聚焦时，把新镜规划为
medium_close / close 并说明信息或情绪落点。若下一句马上由另一人承接且当前句不是独立重点，不制造一次短促单人近景。
同一连续镜头中的收组则规划可见的淡出与重构，不用裸名单删除冒充聚焦。
场景或新镜头第一次显示人物时，若上一拍没有该立绘，规划淡入/reveal；正文明确从左、右或遮挡物后出现时再使用对应方向。
“从设备后站起”“从柜中探头”属于同一空间内的被揭示，必须有 reveal 过程，不能原位换人。多人镜头切成单人时，
要么完整 cut 到 medium_close/close，要么在连续镜头中先淡出同伴再 reframe；只删名单不算聚焦。峰值 close 之后进入普通解释、
接力或关系余波时，规划 release 回 medium/关系镜头，不能让特写无意持续。

action 是身体运动，emoticon 是瞬时心理符号。若同一拍同时存在有证据的身体运动与独立心理闪现，它们不是可替代载体：
拆成两个 performance_intent，或明确要求二者共同兑现；规划 action 后仍要独立扫描 emo。shake 通常伴随明显心理冲击，
hophop 要重点检查兴奋、愤怒或冲动气泡；jump / stiff 只有在另有清楚的惊讶、尴尬、压力等心理信息时才组合。
动作自身已经完整表达身体事实时允许单独使用，不把组合写成固定配方。
规划 action 时描述的是可见身体意图，不是台词的语用标签；“确认、汇报、验证成功”本身不能证明点头或任何具体动作。
物件操作若没有可准确表达的动作资源，可以规划 face_change、camera_change 或有文本依据的 sound，不要用点头类动作代替操作。

计划内部必须自洽：每个 `solo_emphasis` peak 的 `peak_id` 必须同时对应一个从该锚点开始的
`shot_group`，且该组 `members` 只能是主体、`framing` 为 `close` 或 `medium_close`；同一锚点还要有
该主体的 `performance_intents`。`face_arcs` 中每个语义阶段变化锚点，也必须有同位置、同主体的
`performance_intents`，carrier 至少包含 `face_change`、`emoticon` 或 `action` 之一。不要先写峰值或阶段，
再把镜头和表演合同留空；若正文不支持这些条件，就不要声明对应 peak/arc。

输出前再复核一次身体意图：若 purpose 描述的是观众能够独立看见、并能由通用身体动作准确表达的新运动，
给它单独的 `carriers=["action"]` intent；同一锚点需要的 face/emoticon 另写 intent。不要把这种 action 与
face_change/emoticon 塞进 `require_all=false` 的可替代集合，否则执行层只换脸也会误读为已经完成身体表演。
按下按钮、翻页、拿起物件等物件操作本身不等于通用身体 action；没有准确动作载体时，规划有语义依据的
camera_change、sound 或 face_change 来表现操作注意与结果。正文没有独立身体信息时不声明 action，
这条复核不构成动作数量要求。

arrival 只有真实到场证据才规划 enter/reveal；有证据时可以由对白节点上的 enter/reveal 承载，不能把首次露面自动当入场。
后文确认可以把这种后文证据归回人物首次出现的拍点。对象操作、反馈/验证、decision_pause 和 time_bridge 只在正文确有独立
可读状态时写；不能因事件类型补蒙太奇，也不能用峰值之前的停顿冒充结果余波。多人反应可用 action -> relay -> aftershock，
后者不必是前者全体。若 A 的反应成为 B 的刺激，保留所有权，不压成全员同步。

注意：`object_test` 是事件的 kind，不是 phase_order 或 phase_anchors 的值；涉及试机过程时，phase 使用
`object_action`，结果确认使用 `feedback` / `verification`。

听觉载体单独过证据门：只有正文明确出现可听见的声源、启动反馈、机械声、警报、脚步或其他可靠听觉结果时，
才把 sound 放进 carriers；“开始操作”“确认成功”本身不等于有声音。没有独立听觉事实时不要把 sound 写进
require_all=true，也不要为了让 G2 看起来更完整而补音效。若声音只是多个等价表达中的一种，可以保留 sound
作为可选 carrier，但 G2 应按当前可用资源和语义选择，不因计划中出现它就强制添加。

只输出 Schema JSON，不复述台词或解释推理。未提供的可选字段直接省略，不要用空数组填满。
"""


PLANNER_SYSTEM = PLANNER_SYSTEM_COMPACT


SEMANTIC_PLANNER_SYSTEM = """你是视觉小说演出的剧情事件分析器。你只看盲测台词，不看官方演出答案，
也不安排站位、镜头、表情编号、气泡、动作、背景或音效。本次只回答“发生了什么、谁受到影响、结果落到谁身上”。

按因果而不是按说话者切分少量连续事件。每个事件必须覆盖连续台词区间，并明确 stimulus、真正被直接触及的
stimulus_targets、outcome、phase_order，以及 result_owner / aftershock_owner / release_owner。没有相应结果、余波或
释放承受者时填空字符串；不能把当前场景全员自动写成承受者。多人受到同一刺激不代表必须同步反应，先后接力仍然
是不同所有权的反应。

phase_anchors 只标出具有叙事功能的锚点：刺激、发现、操作、反馈、验证、结果、决定停顿、时间桥、余波或接力。
silent=true 仅表示该功能需要一个没有对话框的独立展示拍；有台词的锚点必须为 false。不要为了模仿密度制造空拍。
peak_hints 只标场景内相对升级、关系转折或共同反应，不把每个感叹句都当峰值；同时指出释放位置。

这一步禁止输出任何摄影方案。不要决定单人/双人/三人、左右槽位、cut、reframe、move、reveal、enter 或 exit；
这些由下一阶段在完整事件骨架上单独判断。不要复制台词，不解释推理，只输出 Schema JSON。"""


STAGING_PLANNER_SYSTEM = """你是视觉小说演出的空间与镜头导演。上一步已经给出 SEMANTIC_EVENT_PLAN；
本次最重要的任务是把它变成连续、可验证的镜头时间线。你仍然看不到官方答案，也不选择具体 face_id、气泡、动作、
背景或音效资源。

先为每个事件建立互不重叠的 shot_groups。每组必须说明从 anchor_i 到 hold_until_i 的首选连续范围、完整人物名单、焦点、景别和
变化操作。`members` 表示 anchor 时刻观众实际看得到的立绘，不是事件的全部 participants、未来说话者或可能被刺激的人；
后续人物即使已经参与事件，也要等正文已有到场/在场/被看见证据，或等其对白、reveal、enter、完整 cut 到来后再加入画面。
镜头单位是互动轴和承受关系，不是当前说话者：同一问答、操作或笑点推进时优先持镜；互动轴、刺激承受者、
揭晓、峰值或余波主体改变时可以完整硬切。硬切没有次数配额。单人/双人为默认，只有真实三方互动或共同反应才用三人，
绝不超过三人。

严格区分空间语法：cut 一次重建完整新镜头；reframe 是同一连续镜头内扩组、收组或重排；move 是观众需要看见的让位、
靠近或退开；reveal 是仍在物理场景的人从画外加入当前连续镜头；enter/exit 只表示真实进入/离开物理空间。
完整换组就 cut：角色可以跨 hard cut 保留同一侧，另一位角色可以随新镜头名单替换，不需要为了切镜虚构 move、enter 或 exit。
此类切换必须把完整新镜头写成 cut，不能误写成 hold/reframe/move；只有连续镜头里的真实走入、让位或靠近才用 reveal/reframe/move。

SEMANTIC_EVENT_PLAN 是上一步对正文的可推翻假设，不是隐藏官方答案。先重新核对原台词与当前状态；计划与正文冲突、
证据不足或把对白已经表达的信息重复拆成静默拍时，应保留正文并记录偏离。把仍有正文证据的 silent=true
功能锚点兑现为 silent_beats，并给出参与者和抽象载体要求。result/aftershock 的参与者必须与仍成立的 owner 一致。
peak_hints 转成 peaks：solo_emphasis 必须对应主体单人 close/medium_close；relationship_peak 保留双人；group_reaction
保留二至三名真正共同承受者。所有具体释放点都要让 release_owner 可见。

最后再写 face_arcs 和 performance_intents，它们只描述语义阶段与必须存在的表演层，不写具体资源。不要为了填 Schema
增加表情变化、动作、气泡或特写；但已经声明的阶段变化必须由 face_change / emoticon / action 等可读载体承接。
逐个执行锚点时，要把当前拍与上一有效对白或 silent_beat 比较：若 face_arc 或正文显示阶段已经变化，必须在该锚点
保留至少一种可见 carrier；若没有变化才允许 hold。计划中的 silent_beat 不能在第二阶段被合并成普通对白而失去
独立的表情/动作因果，除非正文重新证明下一句已经完整承载了同一变化。
站位变化要区分“观众看见让位/靠近”与“新构图”：前者规划 move/reframe 并让物理位置跨节点延续，后者用完整
cut 重建名单和位置；不要把人物从一个槽位无解释地瞬移到另一个槽位。背景地点/时间/黑场改变才规划 trans，
普通反打、显现和人数变化不规划 trans；#all;hide 只表示镜头清空或边界，不单独证明叙事退场。
禁止写 FocusLine、jump 等具体 AA 名称。不要复述台词或解释推理，只输出完整 Plan IR JSON。"""


def _semantic_event_schema(
    target_count: int, cast_names: Sequence[str],
) -> dict[str, Any]:
    names = list(dict.fromkeys(cast_names))
    person = {"type": "string", "enum": names}
    person_or_empty = {"type": "string", "enum": ["", *names]}
    anchor_position = {"type": "string", "enum": ["on", "before", "after"]}
    phase_anchor = {
        "type": "object",
        "properties": {
            "anchor_i": {"type": "integer", "minimum": 1, "maximum": target_count},
            "position": anchor_position,
            "phase": {"type": "string", "enum": list(EVENT_PHASES)},
            "owner": person_or_empty,
            "silent": {"type": "boolean"},
            "purpose": {"type": "string"},
        },
        "required": ["anchor_i", "position", "phase", "owner", "silent", "purpose"],
        "additionalProperties": False,
    }
    peak_hint = {
        "type": "object",
        "properties": {
            "subject": person,
            "peak_type": {"type": "string", "enum": list(PEAK_TYPES)},
            "peak_i": {"type": "integer", "minimum": 1, "maximum": target_count},
            "position": anchor_position,
            "release_i": {"type": "integer", "minimum": 0, "maximum": target_count},
            "release_position": {
                "type": "string", "enum": ["on", "before", "after", "next_event", "scene_end"],
            },
            "why": {"type": "string"},
        },
        "required": [
            "subject", "peak_type", "peak_i", "position", "release_i",
            "release_position", "why",
        ],
        "additionalProperties": False,
    }
    event = {
        "type": "object",
        "properties": {
            "event_id": {"type": "string"},
            "start_i": {"type": "integer", "minimum": 1, "maximum": target_count},
            "end_i": {"type": "integer", "minimum": 1, "maximum": target_count},
            "kind": {"type": "string", "enum": list(EVENT_KINDS)},
            "stimulus": {"type": "string"},
            "stimulus_targets": {"type": "array", "items": person},
            "outcome": {"type": "string"},
            "result_owner": person_or_empty,
            "aftershock_owner": person_or_empty,
            "release_owner": person_or_empty,
            "phase_order": {
                "type": "array", "items": {"type": "string", "enum": list(EVENT_PHASES)},
            },
            "phase_anchors": {"type": "array", "items": phase_anchor},
            "peak_hints": {"type": "array", "items": peak_hint},
        },
        "required": [
            "event_id", "start_i", "end_i", "kind", "stimulus", "stimulus_targets",
            "outcome", "result_owner", "aftershock_owner", "release_owner",
            "phase_order", "phase_anchors", "peak_hints",
        ],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"events": {"type": "array", "items": event}},
        "required": ["events"],
        "additionalProperties": False,
    }


def _event_schema(
    target_count: int, cast_names: Sequence[str], *,
    optional_execution_fields: bool = False,
) -> dict[str, Any]:
    person = {"type": "string", "enum": list(dict.fromkeys(cast_names))}
    person_or_empty = {
        "type": "string", "enum": ["", *list(dict.fromkeys(cast_names))],
    }
    stimulus_group = {
        "type": "array", "items": person,
    }
    group = {
        "type": "array", "maxItems": 3, "items": person,
    }
    anchor_position = {"type": "string", "enum": ["on", "before", "after"]}
    carrier_requirement = {
        "type": "object",
        "properties": {
            "any_of": {
                "type": "array", "minItems": 1,
                "items": {"type": "string", "enum": list(PERFORMANCE_CARRIERS)},
            },
            "require_observable_change": {"type": "boolean"},
        },
        "required": ["any_of", "require_observable_change"],
        "additionalProperties": False,
    }
    shot_group = {
        "type": "object",
        "properties": {
            "group_id": {"type": "string"},
            "anchor_i": {"type": "integer", "minimum": 1, "maximum": target_count},
            "hold_until_i": {"type": "integer", "minimum": 1, "maximum": target_count},
            "members": group,
            "focus": person,
            "framing": {"type": "string", "enum": list(FRAMING_INTENTS)},
            "operation": {"type": "string", "enum": list(SHOT_OPERATIONS)},
            "cut_motivation": {"type": "string"},
            "purpose": {"type": "string"},
        },
        "required": [
            "group_id", "anchor_i", "hold_until_i", "members", "focus", "framing",
            "operation", "cut_motivation", "purpose",
        ],
        "additionalProperties": False,
    }
    performance_intent = {
        "type": "object",
        "properties": {
            "anchor_i": {"type": "integer", "minimum": 1, "maximum": target_count},
            "position": anchor_position,
            "subjects": group,
            "carriers": {
                "type": "array", "minItems": 1,
                "items": {"type": "string", "enum": list(PERFORMANCE_CARRIERS)},
            },
            "require_all": {"type": "boolean"},
            "purpose": {"type": "string"},
        },
        "required": ["anchor_i", "position", "subjects", "carriers", "purpose"],
        "additionalProperties": False,
    }
    face_stage = {
        "type": "object",
        "properties": {
            "anchor_i": {"type": "integer", "minimum": 1, "maximum": target_count},
            "position": anchor_position,
            "semantic_state": {"type": "string"},
            "change_reason": {"type": "string"},
        },
        "required": ["anchor_i", "position", "semantic_state", "change_reason"],
        "additionalProperties": False,
    }
    face_arc = {
        "type": "object",
        "properties": {
            "who": person,
            "stages": {"type": "array", "items": face_stage},
            # A narrow compatibility repair for gateways that drift an
            # event-level field into a face arc. Normalization moves it back
            # to the event and records the repair in the plan audit.
            "continuity_goal": {"type": "string"},
        },
        "required": ["who", "stages"],
        "additionalProperties": False,
    }
    silent_beat = {
        "type": "object",
        "properties": {
            "anchor_i": {"type": "integer", "minimum": 1, "maximum": target_count},
            "position": {"type": "string", "enum": ["before", "after"]},
            "phase": {"type": "string", "enum": list(EVENT_PHASES)},
            "purpose": {"type": "string"},
            "participants": group,
            "sound_motivated": {"type": "boolean"},
            "carrier_requirement": carrier_requirement,
        },
        "required": [
            "anchor_i", "position", "phase", "purpose", "participants",
            "sound_motivated", "carrier_requirement",
        ],
        "additionalProperties": False,
    }
    peak = {
        "type": "object",
        "properties": {
            "subject": person,
            "peak_type": {"type": "string", "enum": list(PEAK_TYPES)},
            "peak_i": {"type": "integer", "minimum": 1, "maximum": target_count},
            "position": anchor_position,
            "visual_intent": {"type": "string"},
            "release_i": {"type": "integer", "minimum": 0, "maximum": target_count},
            "release_position": {
                "type": "string", "enum": ["on", "before", "after", "next_event", "scene_end"],
            },
            "why": {"type": "string"},
        },
        "required": [
            "subject", "peak_type", "peak_i", "position", "visual_intent",
            "release_i", "release_position", "why",
        ],
        "additionalProperties": False,
    }
    core_required = [
        "event_id", "start_i", "end_i", "kind", "stimulus", "outcome",
    ]
    execution_required = [
        "stimulus_targets", "result_owner", "aftershock_owner", "release_owner",
        "phase_order", "shot_groups", "focus_turns", "performance_intents",
        "face_arcs", "silent_beats", "peaks", "continuity_goal",
    ]
    event = {
        "type": "object",
        "properties": {
            "event_id": {"type": "string"},
            "start_i": {"type": "integer", "minimum": 1, "maximum": target_count},
            "end_i": {"type": "integer", "minimum": 1, "maximum": target_count},
            "kind": {"type": "string", "enum": list(EVENT_KINDS)},
            "stimulus": {"type": "string"},
            "stimulus_targets": stimulus_group,
            "outcome": {"type": "string"},
            "result_owner": person_or_empty,
            "aftershock_owner": person_or_empty,
            "release_owner": person_or_empty,
            "phase_order": {
                "type": "array", "items": {
                "type": "string", "enum": list(PHASE_SCHEMA_VALUES),
                },
            },
            "shot_groups": {"type": "array", "items": shot_group},
            "focus_turns": {"type": "array", "items": person},
            "performance_intents": {"type": "array", "items": performance_intent},
            "face_arcs": {"type": "array", "items": face_arc},
            "silent_beats": {"type": "array", "items": silent_beat},
            "peaks": {"type": "array", "items": peak},
            "continuity_goal": {"type": "string"},
        },
        # The direct helper keeps the v2 contract for old checkpoint fixtures.
        # Live planner requests use the smaller semantic core so optional
        # staging/performance analysis does not become a fill-in checklist.
        "required": core_required if optional_execution_fields else core_required + execution_required,
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "events": {"type": "array", "items": event},
        },
        "required": ["events"],
        "additionalProperties": False,
    }


def _scene_targets(
    items: Sequence[Mapping[str, Any]], scene: Mapping[str, Any]
) -> list[Mapping[str, Any]]:
    return [
        items[index] for index in scene.get("target_indices") or []
        if 0 <= int(index) < len(items) and items[int(index)].get("kind") == "line"
    ]


def build_scene_planner_request(
    items: Sequence[Mapping[str, Any]], scene: Mapping[str, Any], *,
    previous_plan: Mapping[str, Any] | None = None,
    quality_issues: Sequence[Mapping[str, Any]] = (),
    cast: Mapping[str, Any] | None = None,
    retry_instruction: str = "",
) -> tuple[str, dict[str, Any], list[Mapping[str, Any]]]:
    targets = _scene_targets(items, scene)
    cast_names = [
        str(item.get("who") or "") for item in targets if str(item.get("who") or "")
    ]
    lines = [
        f"{index}. {item.get('who')}: {item.get('text')}"
        for index, item in enumerate(targets, 1)
    ]
    user = (
        f"SCENE_ID={scene.get('scene_id') or ''}\n"
        f"SCENE_TYPE={scene.get('scene_type') or 'other'}\n"
        "DISPLAYABLE_CAST=" + json.dumps(
            [name for name in dict.fromkeys(cast_names) if _is_displayable_cast_member(name, cast)],
            ensure_ascii=False, separators=(",", ":"),
        ) + "\n"
        "OFFSCREEN_NAMED_SPEAKERS=" + json.dumps(
            [name for name in dict.fromkeys(cast_names) if not _is_displayable_cast_member(name, cast)],
            ensure_ascii=False, separators=(",", ":"),
        ) + "\n"
        "请为以下完整场景建立事件计划。编号只用于 start_i/end_i/anchor_i：\n"
        + "\n".join(lines)
    )
    if retry_instruction:
        user += (
            "\n\nPLANNER_PROTOCOL_RETRY\n"
            "上一次规划请求没有通过协议或上游请求暂时失败。请重新完成同一场景的完整计划，"
            "只输出符合当前 Schema 的 JSON；不要加入 Schema 未声明的顶层字段，不要使用不在允许枚举中的 phase。"
            "`object_test` 只能作为事件 kind；phase_order 中试机用 `object_action`，结果确认用 `feedback` 或 `verification`。\n"
            + str(retry_instruction)
        )
    if previous_plan and quality_issues:
        compact_issues = [
            {
                key: issue.get(key)
                for key in ("code", "event_id", "anchor_id", "message")
                if issue.get(key) not in (None, "")
            }
            for issue in quality_issues
            if str(issue.get("severity") or "high") in {"critical", "high"}
        ]
        user += (
            "\n\n上一次计划未通过 G1。请只修复下列结构/语义矛盾，并返回完整场景计划；"
            "不要增加固定数量的镜头或表演：\n"
            + json.dumps(compact_issues, ensure_ascii=False, separators=(",", ":"))
            + "\nPREVIOUS_PLAN\n"
            + json.dumps(previous_plan, ensure_ascii=False, separators=(",", ":"))
        )
    return user, _event_schema(
        len(targets), cast_names, optional_execution_fields=True,
    ), targets


def _anchor_number(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _coerce_string_list(value: Any) -> list[str]:
    """Repair common model shorthand without changing semantic choices.

    Planner responses occasionally serialize an array of names or carriers as
    one whitespace/comma-delimited string.  This is a lossless protocol repair
    for the already-selected values; it is deliberately not a resource or
    art-direction fallback.
    """
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        for separator in (",", "，", "、", "|", "/"):
            text = text.replace(separator, " ")
        values = text.split()
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        values = [str(item).strip() for item in value]
    else:
        return []
    return list(dict.fromkeys(item for item in values if item))


def _normalize_plan_fields(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize only array-shaped fields that models commonly flatten."""
    value = dict(raw)
    protocol_repairs: list[dict[str, Any]] = []
    normalized_arcs = []
    misplaced_goals: list[tuple[int, str]] = []
    for arc_index, arc in enumerate(value.get("face_arcs") or []):
        if not isinstance(arc, Mapping):
            normalized_arcs.append(arc)
            continue
        normalized_arc = dict(arc)
        misplaced = normalized_arc.pop("continuity_goal", None)
        if isinstance(misplaced, str) and misplaced.strip():
            misplaced_goals.append((arc_index, misplaced.strip()))
        normalized_arcs.append(normalized_arc)
    if "face_arcs" in value:
        value["face_arcs"] = normalized_arcs
    phase_order = value.get("phase_order")
    if isinstance(phase_order, list):
        normalized_phases = []
        for phase in phase_order:
            phase_name = str(phase or "")
            replacement = PHASE_COMPAT_ALIASES.get(phase_name, phase_name)
            if replacement != phase_name:
                protocol_repairs.append({
                    "code": "planner_phase_alias",
                    "field": "phase_order",
                    "source_value": phase_name,
                    "value": replacement,
                    "action": "mapped_compat_alias",
                    "reason": "event kind was returned in phase_order",
                })
            normalized_phases.append(replacement)
        value["phase_order"] = normalized_phases
    if misplaced_goals:
        event_goal = value.get("continuity_goal")
        has_event_goal = isinstance(event_goal, str) and bool(event_goal.strip())
        if not has_event_goal:
            value["continuity_goal"] = misplaced_goals[0][1]
        for arc_index, goal in misplaced_goals:
            moved = (
                arc_index == misplaced_goals[0][0]
                and value.get("continuity_goal") == goal
                and not has_event_goal
            )
            protocol_repairs.append({
                "code": "planner_misplaced_event_field",
                "field": "continuity_goal",
                "source_path": f"face_arcs[{arc_index}].continuity_goal",
                "target_path": "continuity_goal" if moved else "",
                "action": "moved_to_event" if moved else "discarded_duplicate",
                "reason": "event-level continuity_goal was nested under face_arc",
            })
    if protocol_repairs:
        value["_protocol_repairs"] = protocol_repairs
    for field in ("stimulus_targets", "focus_turns"):
        if field in value:
            value[field] = _coerce_string_list(value.get(field))
    groups = []
    for group in value.get("shot_groups") or []:
        if not isinstance(group, Mapping):
            groups.append(group)
            continue
        normalized = dict(group)
        if "members" in normalized:
            normalized["members"] = _coerce_string_list(normalized.get("members"))
        groups.append(normalized)
    if "shot_groups" in value:
        value["shot_groups"] = groups
    intents = []
    for intent in value.get("performance_intents") or []:
        if not isinstance(intent, Mapping):
            continue
        normalized = dict(intent)
        for field in ("subjects", "carriers"):
            if field in normalized:
                normalized[field] = _coerce_string_list(normalized.get(field))
        intents.append(normalized)
    if "performance_intents" in value:
        value["performance_intents"] = intents
    silent = []
    for beat in value.get("silent_beats") or []:
        if not isinstance(beat, Mapping):
            continue
        normalized = dict(beat)
        if "participants" in normalized:
            normalized["participants"] = _coerce_string_list(normalized.get("participants"))
        requirement = normalized.get("carrier_requirement")
        if isinstance(requirement, Mapping) and "any_of" in requirement:
            normalized["carrier_requirement"] = {
                **dict(requirement),
                "any_of": _coerce_string_list(requirement.get("any_of")),
            }
        silent.append(normalized)
    if "silent_beats" in value:
        value["silent_beats"] = silent
    return value


def _anchored_record(
    value: Mapping[str, Any], targets: Sequence[Mapping[str, Any]],
    *, anchor_field: str = "anchor_i", id_field: str = "anchor_id",
    start: int = 1, end: int | None = None,
) -> dict[str, Any] | None:
    anchor = _anchor_number(value.get(anchor_field))
    upper = len(targets) if end is None else end
    if not start <= anchor <= upper:
        return None
    return {
        **dict(value),
        id_field: str(targets[anchor - 1].get("annotation_id") or ""),
    }


def normalize_scene_event_plan(
    response: Mapping[str, Any], targets: Sequence[Mapping[str, Any]], scene_id: str,
) -> dict[str, Any]:
    result = []
    protocol_repairs: list[dict[str, Any]] = []
    previous_end = 0
    seen_ids: set[str] = set()
    for ordinal, raw in enumerate(response.get("events") or [], 1):
        if not isinstance(raw, Mapping):
            continue
        raw = _normalize_plan_fields(raw)
        event_repairs = list(raw.pop("_protocol_repairs", []) or [])
        start = int(raw.get("start_i") or 0)
        end = int(raw.get("end_i") or 0)
        if not (1 <= start <= end <= len(targets)):
            continue
        event_id = str(raw.get("event_id") or f"event-{ordinal}").strip()[:80]
        if not event_id or event_id in seen_ids:
            event_id = f"event-{ordinal}"
        seen_ids.add(event_id)
        shot_groups = []
        all_group_values = list(raw.get("shot_groups") or [])
        raw_groups = [value for value in all_group_values if isinstance(value, Mapping)]
        for group_index, group_value in enumerate(raw_groups):
            if isinstance(group_value, Mapping):
                normalized = _anchored_record(
                    group_value, targets, start=start, end=end,
                )
                if normalized is not None:
                    anchor_i = _anchor_number(group_value.get("anchor_i"))
                    hold_until_i = _anchor_number(group_value.get("hold_until_i"))
                    if not anchor_i <= hold_until_i <= end:
                        following = [
                            _anchor_number(value.get("anchor_i"))
                            for value in raw_groups[group_index + 1:]
                            if _anchor_number(value.get("anchor_i")) > anchor_i
                        ]
                        hold_until_i = min(following) - 1 if following else end
                    normalized["hold_until_i"] = hold_until_i
                    normalized["hold_until_id"] = str(
                        targets[hold_until_i - 1].get("annotation_id") or ""
                    )
                    shot_groups.append(normalized)
        for group_value in all_group_values:
            if isinstance(group_value, Sequence) and not isinstance(group_value, (str, bytes)):
                # Read old checkpoints without pretending they contain v2 transition intent.
                shot_groups.append(list(dict.fromkeys(str(name) for name in group_value if str(name))))

        performance_intents = []
        for intent in raw.get("performance_intents") or []:
            if not isinstance(intent, Mapping):
                continue
            normalized = _anchored_record(intent, targets, start=start, end=end)
            if normalized is not None:
                performance_intents.append(normalized)

        face_arcs = []
        for arc in raw.get("face_arcs") or []:
            if not isinstance(arc, Mapping):
                continue
            stages = []
            for stage in arc.get("stages") or []:
                if not isinstance(stage, Mapping):
                    continue
                normalized = _anchored_record(stage, targets, start=start, end=end)
                if normalized is not None:
                    stages.append(normalized)
            if stages:
                face_arcs.append({**dict(arc), "stages": stages})

        silent = []
        for beat in raw.get("silent_beats") or []:
            if not isinstance(beat, Mapping):
                continue
            normalized = _anchored_record(beat, targets, start=start, end=end)
            if normalized is not None:
                silent.append(normalized)

        peaks = []
        for peak in raw.get("peaks") or []:
            if not isinstance(peak, Mapping):
                continue
            normalized = _anchored_record(
                peak, targets, anchor_field="peak_i", id_field="peak_id",
                start=start, end=end,
            )
            if normalized is None:
                continue
            release_position = str(normalized.get("release_position") or "")
            release_i = _anchor_number(normalized.get("release_i"))
            if release_position in {"next_event", "scene_end"}:
                normalized["release_i"] = 0
                normalized["release_id"] = ""
            elif 1 <= release_i <= len(targets):
                normalized["release_id"] = str(
                    targets[release_i - 1].get("annotation_id") or ""
                )
            else:
                continue
            peaks.append(normalized)

        result.append({
            **dict(raw),
            "event_id": event_id,
            "result_owner": str(raw.get("result_owner") or ""),
            "aftershock_owner": str(raw.get("aftershock_owner") or ""),
            "release_owner": str(raw.get("release_owner") or ""),
            "start_id": str(targets[start - 1].get("annotation_id") or ""),
            "end_id": str(targets[end - 1].get("annotation_id") or ""),
            "source_ids": [
                str(targets[index].get("annotation_id") or "")
                for index in range(start - 1, end)
            ],
            "shot_groups": shot_groups,
            "performance_intents": performance_intents,
            "face_arcs": face_arcs,
            "silent_beats": silent,
            "peaks": peaks,
            "overlaps_previous": start <= previous_end,
        })
        protocol_repairs.extend({"event_id": event_id, **dict(repair)} for repair in event_repairs)
        previous_end = max(previous_end, end)
    plan = {"scene_id": str(scene_id), "events": result}
    if protocol_repairs:
        plan["protocol_repairs"] = protocol_repairs
    return plan


def plan_scene_events(
    provider: Any,
    items: Sequence[Mapping[str, Any]],
    scene: Mapping[str, Any],
    *, previous_plan: Mapping[str, Any] | None = None,
    quality_issues: Sequence[Mapping[str, Any]] = (),
    cast: Mapping[str, Any] | None = None,
    on_activity: Any = None,
    retry_instruction: str = "",
    use_stream: bool = True,
) -> dict[str, Any]:
    user, schema, targets = build_scene_planner_request(
        items, scene, previous_plan=previous_plan, quality_issues=quality_issues,
        cast=cast, retry_instruction=retry_instruction,
    )
    if not targets:
        return {"scene_id": str(scene.get("scene_id") or ""), "events": []}
    stream_method = getattr(provider, "complete_json_stream", None)
    if use_stream and callable(stream_method):
        response = stream_method(
            PLANNER_SYSTEM, "", user, schema, on_activity=on_activity,
        )
    else:
        if on_activity:
            on_activity({
                "state": "waiting", "model": str(getattr(provider, "model", "") or ""),
                "received_chars": 0,
            })
        response = provider.complete_json(PLANNER_SYSTEM, "", user, schema)
        if on_activity:
            on_activity({
                "state": "completed", "model": str(getattr(provider, "model", "") or ""),
                "received_chars": 0,
            })
    if not isinstance(response, Mapping):
        raise ValueError("scene planner response must be an object")
    return sanitize_scene_event_plan_for_cast(normalize_scene_event_plan(
        response, targets, str(scene.get("scene_id") or "")
    ), cast)


def _is_displayable_cast_member(
    name: str, cast: Mapping[str, Any] | None,
) -> bool:
    """Whether *name* owns an actual portrait layer in this project."""
    if not name or not isinstance(cast, Mapping):
        return name not in _KNOWN_NARRATOR_NAMES
    value = cast.get(name)
    return bool(
        isinstance(value, Mapping)
        and value.get("portrait")
        and not value.get("narrator")
    )


def sanitize_scene_event_plan_for_cast(
    plan: Mapping[str, Any], cast: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Remove impossible portrait work while preserving offscreen story semantics.

    Named voices such as 老师 and 店员 still belong in stimuli, outcomes and
    relationship prose.  They cannot, however, satisfy a visual performance or
    composition contract.  Keeping that distinction here prevents G2 repair
    from repeatedly trying to invent a portrait layer for them.
    """
    value = copy.deepcopy(dict(plan or {}))
    if not isinstance(cast, Mapping):
        return value
    for event in value.get("events") or []:
        if not isinstance(event, dict):
            continue
        groups = []
        for raw_group in event.get("shot_groups") or []:
            if not isinstance(raw_group, Mapping):
                groups.append(raw_group)
                continue
            group = dict(raw_group)
            original_members = [str(name) for name in group.get("members") or [] if str(name)]
            members = [name for name in original_members if _is_displayable_cast_member(name, cast)]
            offscreen = [name for name in original_members if name not in members]
            if not members:
                continue
            group["members"] = members
            if offscreen:
                group["_offscreen_members"] = offscreen
            if str(group.get("focus") or "") not in members:
                group["focus"] = members[0]
            groups.append(group)
        event["shot_groups"] = groups
        event["focus_turns"] = [
            str(name) for name in event.get("focus_turns") or []
            if _is_displayable_cast_member(str(name), cast)
        ]

        intents = []
        for raw_intent in event.get("performance_intents") or []:
            if not isinstance(raw_intent, Mapping):
                continue
            intent = dict(raw_intent)
            subjects = [
                str(name) for name in intent.get("subjects") or []
                if _is_displayable_cast_member(str(name), cast)
            ]
            if not subjects:
                continue
            intent["subjects"] = subjects
            intents.append(intent)
        event["performance_intents"] = intents
        event["face_arcs"] = [
            dict(arc) for arc in event.get("face_arcs") or []
            if isinstance(arc, Mapping)
            and _is_displayable_cast_member(str(arc.get("who") or ""), cast)
        ]

        silent_beats = []
        for raw_beat in event.get("silent_beats") or []:
            if not isinstance(raw_beat, Mapping):
                continue
            beat = dict(raw_beat)
            participants = [
                str(name) for name in beat.get("participants") or []
                if _is_displayable_cast_member(str(name), cast)
            ]
            if not participants:
                continue
            beat["participants"] = participants
            silent_beats.append(beat)
        event["silent_beats"] = silent_beats
        event["peaks"] = [
            dict(peak) for peak in event.get("peaks") or []
            if isinstance(peak, Mapping)
            and _is_displayable_cast_member(str(peak.get("subject") or ""), cast)
        ]
    return value


def relevant_scene_events(
    plan: Mapping[str, Any] | None, target_ids: Sequence[str]
) -> list[dict[str, Any]]:
    wanted = {str(value) for value in target_ids if str(value)}
    events = []
    for event in (plan or {}).get("events") or []:
        sources = {str(value) for value in event.get("source_ids") or []}
        if sources & wanted:
            events.append(dict(event))
    return events


def project_scene_event_plan(
    plan: Mapping[str, Any] | None, target_ids: Sequence[str],
) -> dict[str, Any]:
    """Project one scene-wide plan without repeating unrelated full events."""
    wanted = {str(value) for value in target_ids if str(value)}
    events = [
        dict(event) for event in (plan or {}).get("events") or []
        if isinstance(event, Mapping)
    ]
    active_indices = [
        index for index, event in enumerate(events)
        if wanted & {str(value) for value in event.get("source_ids") or []}
    ]
    if not active_indices:
        return {"previous_event": None, "active_events": [], "next_event": None}
    first, last = min(active_indices), max(active_indices)
    local_index = {source_id: index for index, source_id in enumerate(target_ids, 1)}
    active = []
    for index in active_indices:
        event = events[index]
        shot_groups = []
        event_sources = [str(value) for value in event.get("source_ids") or []]
        event_order = {source_id: index for index, source_id in enumerate(event_sources)}
        for group in event.get("shot_groups") or []:
            if not isinstance(group, Mapping):
                shot_groups.append(group)
                continue
            anchor_id = str(group.get("anchor_id") or "")
            hold_until_id = str(group.get("hold_until_id") or anchor_id)
            start_at = event_order.get(anchor_id)
            end_at = event_order.get(hold_until_id, start_at)
            if start_at is None or end_at is None:
                continue
            covered = event_sources[start_at:end_at + 1]
            local_covered = [local_index[value] for value in covered if value in local_index]
            if not local_covered:
                continue
            shot_groups.append({
                **dict(group),
                "anchor_i": local_index.get(anchor_id, 0),
                "hold_until_i": max(local_covered),
                "active_from_before_chunk": anchor_id not in local_index,
            })

        performance_intents = []
        for intent in event.get("performance_intents") or []:
            if not isinstance(intent, Mapping):
                continue
            anchor = local_index.get(str(intent.get("anchor_id") or ""))
            if anchor is not None:
                performance_intents.append({**dict(intent), "anchor_i": anchor})

        face_arcs = []
        for arc in event.get("face_arcs") or []:
            if not isinstance(arc, Mapping):
                continue
            ordered_stages = sorted(
                (
                    dict(stage) for stage in arc.get("stages") or []
                    if isinstance(stage, Mapping)
                    and str(stage.get("anchor_id") or "") in event_order
                ),
                key=lambda stage: event_order[str(stage.get("anchor_id") or "")],
            )
            active_stages = [
                stage for stage in ordered_stages
                if str(stage.get("anchor_id") or "") in local_index
            ]
            if not active_stages:
                continue
            first_order = event_order[str(active_stages[0].get("anchor_id") or "")]
            last_order = event_order[str(active_stages[-1].get("anchor_id") or "")]
            previous_stage = next((
                stage for stage in reversed(ordered_stages)
                if event_order[str(stage.get("anchor_id") or "")] < first_order
            ), None)
            next_stage = next((
                stage for stage in ordered_stages
                if event_order[str(stage.get("anchor_id") or "")] > last_order
            ), None)
            stages = []
            if previous_stage:
                stages.append({**previous_stage, "anchor_i": 0, "context_role": "previous"})
            stages.extend({
                **stage,
                "anchor_i": local_index[str(stage.get("anchor_id") or "")],
                "context_role": "active",
            } for stage in active_stages)
            if next_stage:
                stages.append({**next_stage, "anchor_i": 0, "context_role": "next"})
            face_arcs.append({**dict(arc), "stages": stages})

        silent = []
        for beat in event.get("silent_beats") or []:
            anchor = local_index.get(str(beat.get("anchor_id") or ""))
            if anchor is None:
                continue
            silent.append({
                "anchor_i": anchor,
                "position": beat.get("position"),
                "phase": beat.get("phase"),
                "purpose": beat.get("purpose"),
                "participants": beat.get("participants") or [],
                "sound_motivated": bool(beat.get("sound_motivated")),
                "carrier_requirement": dict(beat.get("carrier_requirement") or {}),
            })

        peaks = []
        for peak in event.get("peaks") or []:
            if not isinstance(peak, Mapping):
                continue
            peak_i = local_index.get(str(peak.get("peak_id") or ""))
            release_id = str(peak.get("release_id") or "")
            release_i = local_index.get(release_id) if release_id else 0
            if peak_i is None and release_i is None:
                continue
            projected = dict(peak)
            projected["peak_i"] = peak_i or 0
            projected["release_i"] = release_i or 0
            peaks.append(projected)

        active.append({
            key: event.get(key)
            for key in (
                "event_id", "kind", "stimulus", "outcome", "phase_order",
                "focus_turns", "continuity_goal", "result_owner",
                "aftershock_owner", "release_owner",
                "peak_character", "peak_reason",
            )
        } | {
            "shot_groups": shot_groups,
            "performance_intents": performance_intents,
            "face_arcs": face_arcs,
            "silent_beats": silent,
            "peaks": peaks,
        })
    previous = events[first - 1] if first > 0 else None
    following = events[last + 1] if last + 1 < len(events) else None
    return {
        "previous_event": (
            {"event_id": previous.get("event_id"), "outcome": previous.get("outcome")}
            if previous else None
        ),
        "active_events": active,
        "next_event": (
            {"event_id": following.get("event_id"), "stimulus": following.get("stimulus")}
            if following else None
        ),
    }


_KNOWN_NARRATOR_NAMES = {"旁白", "narrator", "narration"}


def _narrator_names(cast: Mapping[str, Any] | None = None) -> set[str]:
    """Return names that cannot satisfy a visible-character requirement."""
    names = set(_KNOWN_NARRATOR_NAMES)
    if isinstance(cast, Mapping):
        for name, value in cast.items():
            if not isinstance(value, Mapping):
                continue
            if value.get("narrator") or value.get("portrait") is False:
                names.add(str(name))
    return {name for name in names if name}


def _displayable_participants(
    values: Sequence[Any] | None, *, cast: Mapping[str, Any] | None = None,
) -> set[str]:
    return {
        str(value) for value in values or []
        if str(value) and str(value) not in _narrator_names(cast)
    }


def _beat_people(beat: Mapping[str, Any]) -> set[str]:
    people = {str(beat.get("who") or "")}
    people.update(str(value) for value in beat.get("visible_characters") or [])
    people.update(
        str(reaction.get("who") or "")
        for reaction in beat.get("reactions") or []
        if isinstance(reaction, Mapping)
    )
    people.discard("")
    return people


def _beat_reactors(beat: Mapping[str, Any]) -> set[str]:
    people = {str(beat.get("who") or "")}
    people.update(
        str(reaction.get("who") or "")
        for reaction in beat.get("reactions") or []
        if isinstance(reaction, Mapping)
    )
    people.discard("")
    return people


def _beat_carriers(beat: Mapping[str, Any]) -> set[str]:
    reactions = [
        reaction for reaction in beat.get("reactions") or []
        if isinstance(reaction, Mapping)
    ]
    carriers: set[str] = set()
    if beat.get("face") or any(reaction.get("face") for reaction in reactions):
        carriers.add("face_change")
    if beat.get("emo") or any(reaction.get("emo") for reaction in reactions):
        carriers.add("emoticon")
    if beat.get("act") or any(reaction.get("act") for reaction in reactions):
        carriers.add("action")
    if beat.get("se"):
        carriers.add("sound")
    if any((
        beat.get("visible_characters"), beat.get("positions"),
        beat.get("shot_transition"), beat.get("shot_operation"),
    )):
        carriers.add("camera_change")
    if any((beat.get("move"), beat.get("reveal"), beat.get("enter"), beat.get("exit"))):
        carriers.add("movement")
    if any((beat.get("reveal"), beat.get("enter"), beat.get("exit"))):
        carriers.add("entry_exit")
    if any((beat.get("bg"), beat.get("bgfx"), beat.get("trans"), beat.get("place"))):
        carriers.add("background_change")
    if int(beat.get("wait_ms") or 0) > 0:
        carriers.add("pose_hold")
    return carriers


def _phase_payload_error(
    requirement: Mapping[str, Any], beat: Mapping[str, Any],
    *, cast: Mapping[str, Any] | None = None,
) -> str:
    phase = str(requirement.get("phase") or "")
    if phase == "cue":
        if requirement.get("sound_motivated") and not str(beat.get("se") or ""):
            return "cue 缺少计划要求的声音载体"
        if not any((
            beat.get("se"), beat.get("act"), beat.get("emo"), beat.get("face"),
            beat.get("fx"), beat.get("bg"), beat.get("bgfx"), beat.get("trans"),
            beat.get("reveal"), beat.get("enter"), beat.get("reactions"),
        )):
            return "cue 只有空等待，没有声画载体"
    elif phase == "reveal":
        if str(requirement.get("_event_kind") or "") == "arrival" and not beat.get("enter"):
            return "arrival 的 reveal 阶段没有使用真实 enter"
        if not any((
            beat.get("reveal"), beat.get("enter"), beat.get("shot_transition"),
            beat.get("visible_characters"),
        )):
            return "reveal 没有显现、进入或镜头重建"
    elif phase == "group_reaction":
        people = _beat_reactors(beat)
        participants = _displayable_participants(
            requirement.get("participants"), cast=cast,
        )
        if len(people) < 2 or (participants and not participants <= people):
            return "group_reaction 没有在同一拍兑现全部同步反应者"
        stimulus_targets = {
            str(value) for value in requirement.get("_stimulus_targets") or [] if str(value)
        }
        if stimulus_targets and not people <= stimulus_targets:
            return "group_reaction 包含未共同承受该刺激的人物"
    elif phase in {"action", "object_action"}:
        if not any((beat.get("act"), beat.get("se"), beat.get("face"))):
            return f"{phase} 没有动作、声音或操作反馈"
    elif phase in {"feedback", "verification"}:
        if not any((
            beat.get("face"), beat.get("emo"), beat.get("act"), beat.get("se"),
            beat.get("reactions"),
        )):
            return f"{phase} 没有新的可读反馈或确认变化"
    elif phase == "result":
        if not any((
            beat.get("face"), beat.get("emo"), beat.get("act"), beat.get("se"),
            beat.get("reactions"),
        )):
            return "result 没有可读的结果变化"
    elif phase == "decision_pause":
        if int(beat.get("wait_ms") or 0) <= 0:
            return "decision_pause 没有实际停顿"
    elif phase == "time_bridge":
        if int(beat.get("wait_ms") or 0) <= 0 or not any((
            beat.get("se"), beat.get("bg"), beat.get("bgfx"), beat.get("trans"),
        )):
            return "time_bridge 只有空等待，没有连接前后时间的声画载体"
    elif phase in {"focus_handoff", "relay"}:
        if not any((
            beat.get("visible_characters"), beat.get("shot_transition"),
            beat.get("face"), beat.get("emo"), beat.get("act"),
        )):
            return f"{phase} 没有焦点承接"
    elif phase == "aftershock":
        if int(beat.get("wait_ms") or 0) <= 0 and not any((
            beat.get("face"), beat.get("emo"), beat.get("act"),
            beat.get("exit"), beat.get("reactions"),
            beat.get("visible_characters"), beat.get("positions"),
            beat.get("shot_transition"), beat.get("shot_operation"),
        )):
            return "aftershock 没有余波"
    requirement_spec = requirement.get("carrier_requirement")
    if isinstance(requirement_spec, Mapping):
        expected = {
            str(value) for value in requirement_spec.get("any_of") or [] if str(value)
        }
        if not expected:
            return f"{phase or 'silent'} 没有声明可读载体"
        observed = _beat_carriers(beat)
        if not expected & observed:
            return (
                f"{phase or 'silent'} 没有兑现计划载体；"
                f"需要 {'/'.join(sorted(expected))}，实际 {'/'.join(sorted(observed)) or '空'}"
            )
    return ""


def event_plan_fulfillment_errors(
    plan: Mapping[str, Any] | None,
    target_ids: Sequence[str],
    beats: Sequence[Mapping[str, Any]],
    *, cast: Mapping[str, Any] | None = None,
) -> list[str]:
    """Return missing required silent phases owned by the current chunk."""
    wanted = {str(value) for value in target_ids if str(value)}
    requirements = []
    phase_orders: dict[str, dict[str, int]] = {}
    for event in (plan or {}).get("events") or []:
        if not isinstance(event, Mapping):
            continue
        event_id = str(event.get("event_id") or "event")
        phase_orders[event_id] = {
            str(phase): index
            for index, phase in enumerate(event.get("phase_order") or [])
            if str(phase)
        }
        for requirement in event.get("silent_beats") or []:
            anchor_id = str(requirement.get("anchor_id") or "")
            if anchor_id in wanted:
                requirements.append((event_id, {
                    **dict(requirement),
                    "_event_kind": str(event.get("kind") or ""),
                    "_stimulus_targets": list(event.get("stimulus_targets") or []),
                }))
    unused = set(range(len(beats)))
    errors = []
    target_order = {str(source_id): index for index, source_id in enumerate(target_ids)}
    matched_timeline: dict[str, list[tuple[tuple[int, int, int], int, str]]] = {}
    for event_id, requirement in requirements:
        anchor_id = str(requirement.get("anchor_id") or "")
        position = str(requirement.get("position") or "")
        phase = str(requirement.get("phase") or "")
        allowed_reasons = _PHASE_BEAT_REASONS.get(phase, set())
        matching = [
            index for index in sorted(unused)
            if str(beats[index].get("anchor_id") or "") == anchor_id
            and str(beats[index].get("position") or "") == position
            and (
                not allowed_reasons
                or str(beats[index].get("reason") or "") in allowed_reasons
            )
        ]
        participants = _displayable_participants(
            requirement.get("participants"), cast=cast,
        )
        if participants and phase != "group_reaction":
            matching = [
                index for index in matching
                if participants & _beat_people(beats[index])
            ]
        if not matching:
            errors.append(
                f"{event_id}:{phase}@{anchor_id}/{position} 未输出计划要求的无对话框拍"
            )
            continue
        chosen = matching[0]
        unused.discard(chosen)
        phase_rank = phase_orders.get(event_id, {}).get(phase)
        if phase_rank is not None:
            beat_position = str(beats[chosen].get("position") or "after")
            matched_timeline.setdefault(event_id, []).append((
                (
                    target_order.get(anchor_id, len(target_order)),
                    0 if beat_position == "before" else 2,
                    chosen,
                ),
                phase_rank,
                phase,
            ))
        payload_error = _phase_payload_error(requirement, beats[chosen], cast=cast)
        if payload_error:
            errors.append(f"{event_id}:{payload_error}")
    for event_id, timeline in matched_timeline.items():
        previous_rank = -1
        for _actual_order, phase_rank, phase in sorted(timeline):
            if phase_rank < previous_rank:
                errors.append(f"{event_id}:{phase} 的实际锚点早于其依赖阶段")
            previous_rank = max(previous_rank, phase_rank)
    return errors
