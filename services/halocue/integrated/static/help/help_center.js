(function () {
  'use strict';

  const pages = [
    { id: 'start', category: 'start', title: '从这里开始', summary: '先选作品，再进入构思、大纲或正文。', status: '可用', sections: [
      ['先找入口', '「作品」列出本机故事；新建或打开后，顶栏提供「构思、大纲、正文、资料、定稿」。小窗口里用「当前创作视图」下拉框切换。左侧「创作」会回到这部作品最近的创作视图。'],
      ['不用先配置所有环境', '手写、整理资料和导入人物可以先做。真实 AI 需要在「设置 → 模型服务」配置；AA 制作环境只在需要对应资源、编译或安装时配置。「本地模拟」不是实际模型生成。'],
      ['已有文稿', '先选择或建立文稿所属作品，再从构思页选择「导入已有内容」。先预览和确认归属，导入不会直接覆盖已有正文。'],
      ['制作入口', '已有定稿时进入「AA 制作」；也可从本机文件或粘贴文本开始。写作定稿与制作草稿是不同的版本，后续改写不会自动替换旧制作输入。']
    ]},
    { id: 'first-scene', category: 'start', title: '完成第一场', summary: '写下正文，保存，再按需要请助手补充。', status: '可用', sections: [
      ['找到场景', '在作品的「大纲」视图选择章节，点击「建立第一场」或「新增场景」，填写名称、地点和目标。保存后进入对应正文。方向仍待确认时，先完成界面提示的作品决定；不要把创建结构误当成自动生成正文。'],
      ['自己写', '点击「写下第一句」开始输入。可以把段落设为旁白、动作或对白；对白需要填写说话人。桌面将鼠标移到段落之间显示插入按钮，小窗口保留可点按的入口。'],
      ['保存后再交给助手', '点「保存正文」或 Ctrl / ⌘ + S 建立正文修订。未保存时助手不能读取新内容；助手旁的「保存正文」只保存，不会顺便发送要求。'],
      ['完成与下一步', '正文保存后可以继续编辑、与助手讨论，或检查本场。准备制作时再去「定稿」完成连续性和发布检查，明确处理本场记忆，最后生成制作定稿。']
    ]},
    { id: 'story-structure', category: 'start', title: '作品、卷、章和场景', summary: '先把结构摆好，后面写起来会轻松很多。', status: '可用', sections: [
      ['作品是什么', '作品保存全作方向、人物和世界观的长期信息。一个作品可以包含多个卷和章。'],
      ['场景怎么划分', '一次连续的时间和地点变化，通常划成一个场景。场景太大，AI 会抓不住重点；场景太小，审查会变得琐碎。'],
      ['推荐的最小结构', '先建立一个作品、一个卷、一个章和一个场景。确认第一场能正常发布后，再继续扩展。'],
      ['需要修改结构时', '章节和场景使用稳定 ID，改名或调整顺序不会改变身份。调整结构后，重新检查涉及的正文和定稿依赖；不要直接修改数据库或删除文件。']
    ]},
    { id: 'writing', category: 'write', title: '写作工作台', summary: '同一部作品中切换视图，不用在多个独立模块之间搬内容。', status: '可用', sections: [
      ['五个创作视图', '「构思」讨论全作方向；「大纲」安排章节与场景；「正文」手写和审查修改；「资料」管理本作人物与事实；「定稿」检查并冻结本次制作用稿。'],
      ['大纲到正文', '在大纲的推荐场景点「开始写第一场」或「继续写这一场」。也可从下面的目录选择其他场景。打开场景只切换工作位置，不会自动调用模型。'],
      ['窗口联动', '正文和本场助手指向同一个场景；「审查改动」回到正文中的修改项。窄窗口在正文和助手之间切换，仍保留当前场景。正文保持阅读宽度，不强行铺满窗口。'],
      ['未保存与冲突', '离开未保存正文前会让你决定继续编辑还是放弃。本地临时输入不等于已保存修订；刷新、关闭或放弃前请保存。遇到版本冲突先核对新版本，不要反复覆盖。']
    ]},
    { id: 'revision', category: 'write', title: '正文修订和 Diff', summary: '看清新增、删除和替换，只应用你选择的部分。', status: '可用', sections: [
      ['谁可以改正文', '手写内容在你点击保存后成为新修订。Agent 返回候选，未采纳前不会替换正式正文。'],
      ['查看改动', '打开「待审修改」查看每项的原文和候选；新增、删除、替换会分别标出。完整正文预览包含全部候选，不表示全部都会写入。'],
      ['只采纳一部分', '勾选想保留的修改，再点击「应用 N 项修改」。未勾选项不会写入；无需为了保留一句话先拒绝整份候选。也可以退回继续讨论。'],
      ['应用之后', '应用会建立新的正文修订，旧审查可能因此失效。发现不合适可继续手写修订或提出新要求；不要把备份恢复当成段落撤销操作。']
    ]},
    { id: 'proposal-review', category: 'write', title: '候选审查与定稿', summary: '分清正文候选、制作定稿和 AA 演出草稿。', status: '可用', sections: [
      ['写作候选', '在正文中查看增删改，勾选并应用需要的修改。人物、事实等资料候选也要先核对，确认后才进入正式资料。'],
      ['检查定稿', '保存正文并完成本场审查；按内容整理长期记忆，或明确确认本场无需沉淀。然后在「定稿」先检查跨场景连续性，再检查发布完整性。'],
      ['生成制作定稿', '检查覆盖当前正文、资料和依赖后，点击冻结按钮建立不可变定稿。修改正文或依赖后，需要重新检查；旧定稿仍保留原内容。'],
      ['制作审查是下一步', 'AA 制作的卡片用于检查角色映射、素材和演出。那里可以编辑和逐卡确认制作草稿，但不会回写原来的写作定稿。编译生成 AA 工程，不是编译写作定稿本身。']
    ]},
    { id: 'references', category: 'write', title: '人物与设定资料', summary: '资料属于作品，来源和采用状态分开记录。', status: '可用', sections: [
      ['资料与素材的区别', '「资料」保存人物、世界规则、剧情记录和参考文件，用于写作理解。「素材」保存立绘、背景、声音等制作资源；有文字资料不表示已有对应图片。'],
      ['导入和复用人物', '在「资料 → 人物库 → 添加人物」选择新建自定义人物、导入 JSON 或「从其他作品选取」。跨作品复制保留来源和完整档案，复制后先待核对，不修改来源作品。'],
      ['原作来源不是官方认证', '基于官方剧情整理的人物参考不等于发行方发布的人物卡。查看档案的出处、验证报告和证据状态；未核实的摘录不能当成已核对原文。'],
      ['让助手使用', '资料保存、资料已确认和本场已选用是不同状态。核对并确认后，再检查本场上下文中的人物和资料范围。跨作品资料不会自动共享。']
    ]},
    { id: 'activity', category: 'write', title: '活动与待处理事项', summary: '运行结束不等于修改已经采纳。', status: '可用', sections: [
      ['四种筛选', '「运行中」显示准备或正在执行的任务；「待处理」包括等待决定与失败记录；「历史」保留已完成和已停止记录；「全部」查看完整列表。'],
      ['定位结果', '从记录点击「打开对话」「查看待审修改」或「查看场景」。本机制作活动单独列出并跨作品显示，操作前核对关联项目。'],
      ['自动更新的边界', '活动页可见时会自动读取新状态，离开或隐藏后停止该页刷新。刷新不自动重试任务、不调用模型，也不代你采纳候选。连接失败时会说明记录可能不是最新。'],
      ['失败后', '查看失败原因，再决定是否明确重试。旧失败记录会保留；存在待审结果时先核对，不要把多次重试当成完成确认。']
    ]},
    { id: 'ai', category: 'write', title: 'AI 和 Agent', summary: '知道模型会做什么，也知道它不会做什么。', status: '需要本机配置', sections: [
      ['Fake Provider 和真实模型', 'Fake Provider 只用于测试界面和接口。真实模型在“设置 → 模型服务”中配置：选择服务商，核对协议与地址，填写模型名及所需 API Key。先“测试连通性”，再选择用途并“保存并立即启用”。写作与 AA 制作分别保存和反馈结果。'],
      ['Agent 可以做什么', 'Agent 可以根据当前场景、人物卡和已确认资料提出演出建议，也可以生成审查项。'],
      ['Agent 不会做什么', 'Agent 不会直接发布正文，不会绕过人工审查修改 ScriptRelease，也不会替你决定最终演出。'],
      ['失败时怎么办', '超时、429 或 5xx 通常可以重试。改过模型配置后，旧任务需要按当前配置重新开始。']
    ]},
    { id: 'production', category: 'produce', title: 'AA 制作', summary: '把确认过的 ScriptRelease 变成 AA 工程。', status: '可用', sections: [
      ['开始前', '先连接自己的 AzureArchive 工作区。HaloCue 只读取资源索引，不会把资源复制进公开包。'],
      ['制作顺序', '创建制作任务，绑定角色，处理背景和音效请求，再逐卡审查。'],
      ['编译和安装', '在审查页展开「交付前检查」，分别查看编译和安装缺什么；可定位问题卡片、待审卡片或打开制作环境。按钮只定位，不会自动编译或安装。安装前仍需确认分类和剧情名称。'],
      ['重复安装', '同一个 Build 不允许重复安装，避免误覆盖 AA 工程。安装前请保留自己的 AA 工程备份。']
    ]},
    { id: 'compile-install', category: 'produce', title: '编译、安装和回退', summary: '编译是检查，安装才会写入你的 AA 工作区。', status: '可用', sections: [
      ['编译前检查', '确认所有卡片已审、角色映射完整、背景和音效都能找到。检查失败时先按问题卡片逐项处理。'],
      ['安装位置', '安装对话框会显示最终分类、剧情名称、.aap 文件和素材目录。先确认路径，再点安装。'],
      ['安装后验证', '在 AA 中选择“打开项目”，打开界面显示的 .aap 文件。HaloCue 不会修改 AA 的最近项目记录。'],
      ['发现安装错误', '先关闭 AA，再保留安装结果和日志。不要反复安装同一个 Build；需要重新生成时，创建新的草稿或 Build。']
    ]},
    { id: 'assets', category: 'produce', title: '素材、Spine 和授权', summary: '哪些文件可以用，哪些文件不能放进公开包。', status: '需要本机配置', sections: [
      ['自定义素材', '素材导入后会登记稳定 Identifier，并复制到当前剧情的独立目录。正在被草稿引用的素材不能直接删除。'],
      ['Spine', 'Spine 只在需要骨骼预览或表情分析时使用。没有 Spine 时，普通剧本编辑、审查和编译仍可进行。'],
      ['公开包边界', '公开版不包含 Spine、游戏资源、个人骨骼、图集、音频或用户作品。请使用自己合法获得的文件。']
    ]},
    { id: 'asset-troubleshooting', category: 'produce', title: '素材找不到怎么办', summary: '先判断是路径、索引，还是授权资源本身的问题。', status: '需要本机配置', sections: [
      ['角色或背景显示缺失', '确认 AzureArchive 路径指向真实安装目录，再重新建立资源索引。索引完成前，预览可能显示为空。'],
      ['自定义素材没有出现', '检查文件是否放在 bgs、sounds 或 characters 子目录，并确认文件名没有被系统拦截。扫描后仍无结果，可用“从本地导入”单独登记。'],
      ['Spine 不能预览', '普通写作和编译不依赖 Spine。需要骨骼预览时，再到设置里选择可用的 Spine CLI，并检查版本是否匹配。'],
      ['授权边界', '素材能被本机读取，不代表可以公开分发。发布前逐项确认授权，公开包只保留程序本身和必要说明。']
    ]},
    { id: 'data', category: 'maintain', title: '数据、迁移和更新', summary: '备份好数据，再升级程序。', status: '可用', sections: [
      ['数据在哪里', '默认目录是 %LOCALAPPDATA%\\HaloCue。程序文件和用户作品分开保存。'],
      ['0.9.3 到 1.0', '发现旧数据后，先点“先备份”，再选择“备份并导入”。系统只复制已知文件，不覆盖已经存在的 1.0 文件。'],
      ['自动更新', '发现新版本时只提示，不会静默安装。确认后下载，退出 HaloCue，再由 HaloCueUpdater.exe 替换程序。'],
      ['更新失败', '旧版本会保留。检查网络、磁盘空间和安装目录权限，也可以手动下载对应 Release。']
    ]},
    { id: 'backup-restore', category: 'maintain', title: '备份、恢复和换电脑', summary: '程序可以重装，作品和配置要靠你自己的备份。', status: '可用', sections: [
      ['备份什么', '备份 %LOCALAPPDATA%\\HaloCue 中的用户数据。API Key 会单独保存在系统凭据区，换电脑前需要在新电脑重新配置。'],
      ['什么时候备份', '迁移前、更新前和大批量导入素材前各备份一次。备份目录会带时间戳，不会覆盖旧备份。'],
      ['恢复旧版本', '退出 HaloCue，把当前数据目录改名，再把备份目录复制回原位置。恢复前先关闭正在运行的 HaloCue 和 HaloCueUpdater。'],
      ['换电脑', '复制用户数据和自己的素材，重新安装 HaloCue 与 AzureArchive，再在设置里重新选择路径和模型连接。']
    ]},
    { id: 'update', category: 'maintain', title: '自动更新', summary: '后台检查，用户确认，失败可回滚。', status: '可用', sections: [
      ['检查什么时候发生', '启动后会在后台检查一次，之后大约每 24 小时检查一次。检查失败不会阻止你写作。'],
      ['安装前会看到什么', '提示会显示版本号、发布日期、更新说明和包大小。只有你确认后才会下载和替换程序。'],
      ['更新过程中', '程序退出后由 HaloCueUpdater 替换文件。用户数据目录不会被更新包覆盖。'],
      ['失败怎么处理', '下载中断、校验失败、没有写权限或启动检查失败时，程序保留旧版本并恢复备份。也可以从 Release 页面手动下载。']
    ]},
    { id: 'troubleshooting', category: 'maintain', title: '常见问题', summary: '先按现象找答案，不需要理解内部实现。', status: '可用', sections: [
      ['窗口打不开', '确认 WebView2 已安装，退出其他 HaloCue 实例，再运行“检查运行环境.cmd”。'],
      ['模型连接失败', '检查地址、模型名和 Key，回到“设置”重新测试文字连接。'],
      ['找不到 AA 或 Spine', '重新选择真实的 AzureArchive.exe。Spine 只在需要骨骼功能时配置。'],
      ['仍然解决不了', '在设置中复制运行环境诊断。诊断不包含 API Key、正文和个人素材路径。']
    ]},
    { id: 'diagnostics', category: 'maintain', title: '提交诊断信息', summary: '只收集排查需要的内容，不把作品和密钥发出去。', status: '可用', sections: [
      ['复制诊断', '打开设置，找到“运行环境诊断”，复制文本或保存文件。提交前先检查里面没有你不想公开的本地路径。'],
      ['诊断包含什么', '包括版本、系统、端口、组件状态、AA 是否识别和最近一次错误代码。它不包含 API Key、模型密钥、正文和素材文件。'],
      ['反馈时附上什么', '写清楚你点了什么、预期是什么、实际发生了什么，再附上诊断和对应时间。不要只发“不能用”。'],
      ['反馈服务器异常', '反馈接口暂时不可用时，信息会留在本地等待重试。你仍然可以继续写作和制作。']
    ]}
  ];

  function textBlock(parent, value) {
    String(value).split('\n').forEach(function (line, index) {
      if (index) parent.appendChild(document.createElement('br'));
      parent.appendChild(document.createTextNode(line));
    });
  }

  function mount(drawer) {
    if (!drawer || drawer.dataset.helpCenterMounted === '1') return;
    drawer.dataset.helpCenterMounted = '1';
    const legacy = drawer.querySelector('.help-sections');
    if (legacy) legacy.hidden = true;
    const toolbar = drawer.querySelector('.help-toolbar');
    if (toolbar) toolbar.remove();
    const shell = document.createElement('div'); shell.className = 'help-doc-layout';
    const nav = document.createElement('aside'); nav.className = 'help-doc-sidebar';
    const navTitle = document.createElement('h3'); navTitle.textContent = '手册目录'; nav.appendChild(navTitle);
    const navList = document.createElement('div'); navList.className = 'help-doc-nav'; nav.appendChild(navList);
    const article = document.createElement('main'); article.className = 'help-doc-main';
    const heading = document.createElement('header'); heading.className = 'help-doc-heading';
    const kicker = document.createElement('span'); kicker.className = 'help-kicker'; kicker.textContent = 'HALOCUE 1.0';
    const title = document.createElement('h2'); const summary = document.createElement('p'); summary.className = 'help-doc-summary';
    const badge = document.createElement('span'); badge.className = 'help-doc-status'; heading.append(kicker, title, summary, badge);
    const content = document.createElement('div'); content.className = 'help-doc-content'; article.append(heading, content);
    const toc = document.createElement('aside'); toc.className = 'help-doc-toc';
    const tocTitle = document.createElement('h3'); tocTitle.textContent = '本页内容'; const tocList = document.createElement('nav'); toc.append(tocTitle, tocList);
    shell.append(nav, article, toc); drawer.appendChild(shell);
    let current = pages[0];
    function renderNav(filter, query) {
      navList.replaceChildren();
      const matches = pages.filter(function (page) { const haystack = (page.title + page.summary + page.sections.map(function (part) { return part.join(' '); }).join(' ')).toLowerCase(); return (filter === 'all' || page.category === filter) && (!query || haystack.includes(query)); });
      matches.forEach(function (page) { const button = document.createElement('button'); button.type = 'button'; button.className = 'ghost'; button.textContent = page.title; button.classList.toggle('is-active', page.id === current.id); button.addEventListener('click', function () { current = page; render(); }); navList.appendChild(button); });
      if (!matches.some(function (page) { return page.id === current.id; }) && matches[0]) { current = matches[0]; render(); }
    }
    function render() {
      title.textContent = current.title; summary.textContent = current.summary; badge.textContent = current.status;
      content.replaceChildren(); tocList.replaceChildren();
      current.sections.forEach(function (part, index) { const section = document.createElement('section'); section.className = 'help-doc-section'; const h = document.createElement('h3'); h.id = 'help-' + current.id + '-' + index; h.textContent = part[0]; const p = document.createElement('p'); textBlock(p, part[1]); section.append(h, p); content.appendChild(section); const link = document.createElement('a'); link.href = '#' + h.id; link.textContent = part[0]; link.addEventListener('click', function (event) { event.preventDefault(); article.scrollTop = h.offsetTop; }); tocList.appendChild(link); });
      renderNav(activeFilter, activeQuery);
    }
    let activeFilter = 'all'; let activeQuery = '';
    const filters = document.createElement('div'); filters.className = 'help-doc-filters';
    [['all', '全部'], ['start', '开始使用'], ['write', '写作与 AI'], ['produce', '制作与素材'], ['maintain', '迁移与排障']].forEach(function (item) { const button = document.createElement('button'); button.type = 'button'; button.className = 'ghost'; button.textContent = item[1]; button.classList.toggle('is-active', item[0] === activeFilter); button.addEventListener('click', function () { activeFilter = item[0]; filters.querySelectorAll('button').forEach(function (other) { other.classList.toggle('is-active', other === button); }); renderNav(activeFilter, activeQuery); }); filters.appendChild(button); });
    const search = document.createElement('input'); search.type = 'search'; search.className = 'help-doc-search'; search.placeholder = '搜索手册'; search.addEventListener('input', function () { activeQuery = search.value.trim().toLowerCase(); renderNav(activeFilter, activeQuery); });
    nav.prepend(search, filters);
    render();
  }

  window.HaloCueHelpPages = pages;
  window.HaloCueHelpCenter = { mount: mount };
})();
