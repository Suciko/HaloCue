(function () {
  'use strict';

  const pages = [
    { id: 'start', category: 'start', title: '从这里开始', summary: '先把程序打开，再完成第一场。', status: '可用', sections: [
      ['你会做什么', '这一页带你完成最短流程：打开 HaloCue、选择 AzureArchive、建立作品、写一句对白，并生成第一份审查草稿。'],
      ['开始前准备', '准备 Windows 10 或 Windows 11、WebView2 Runtime，以及你自己安装的 AzureArchive。HaloCue 不附带游戏资源。'],
      ['操作步骤', '解压 ZIP，双击 HaloCue.exe。打开“设置”，选择 AzureArchive.exe。然后点“选择剧本”，打开 .txt 或 .md 文件。'],
      ['下一步', '如果你还没有剧本，先看“完成第一场”；如果程序打不开，直接看“程序无法启动”。']
    ]},
    { id: 'first-scene', category: 'start', title: '完成第一场', summary: '从一段文字到一份可以审查的草稿。', status: '可用', sections: [
      ['建立结构', '在“作品”中填写作品名，确认全作方向，再建立卷、章和场景。场景是一次写作和审查的最小单位。'],
      ['写正文', '推荐一行一个说话者，例如：\n老师: 久等了。\n乃爱: 我们现在出发吧。'],
      ['生成和审查', '需要 AI 时先测试模型。不需要 AI 时选择“仅转换格式”。生成后逐张检查卡片，确认后才会进入发布。'],
      ['完成的标志', '发布页审查通过，AA 制作页没有待处理问题，并且已经生成工程文件。']
    ]},
    { id: 'story-structure', category: 'start', title: '作品、卷、章和场景', summary: '先把结构摆好，后面写起来会轻松很多。', status: '可用', sections: [
      ['作品是什么', '作品保存全作方向、人物和世界观的长期信息。一个作品可以包含多个卷和章。'],
      ['场景怎么划分', '一次连续的时间和地点变化，通常划成一个场景。场景太大，AI 会抓不住重点；场景太小，审查会变得琐碎。'],
      ['推荐的最小结构', '先建立一个作品、一个卷、一个章和一个场景。确认第一场能正常发布后，再继续扩展。'],
      ['需要修改结构时', '改名和调整顺序不会删除正文。删除场景前先确认没有草稿或发布版本引用它。']
    ]},
    { id: 'writing', category: 'write', title: '写作工作台', summary: '理解作品、场景、正文和发布之间的关系。', status: '可用', sections: [
      ['作品和场景', '作品是最大的范围。卷和章用来整理结构，场景是 Agent 读取和审查的边界。'],
      ['三个阶段', '细纲用来整理顺序和上下文；正文用来写对白和旁白；发布用来检查并冻结 ScriptRelease。'],
      ['修改正文', '模型建议先进入 Proposal。打开 Diff，确认改动后再点“采纳”。不满意就拒绝，不会改动当前正文。'],
      ['遇到冲突', '多个窗口同时修改时，版本不一致会显示冲突。系统不会替你覆盖别人的修改。']
    ]},
    { id: 'revision', category: 'write', title: '正文修订和 Diff', summary: '把修改控制在你看得见、退得回的范围内。', status: '可用', sections: [
      ['谁可以改正文', '你可以直接编辑当前正文。Agent 只能提交 Proposal，不能跳过审查写入发布版本。'],
      ['查看 Diff', '打开 Proposal 后，左边是原文，右边是建议。新增、删除和替换都会标出来。先看上下文，再决定是否采纳。'],
      ['采纳一部分', '如果只想要其中几处，可以先拒绝整份 Proposal，再把需要的句子手动改进正文。1.0 不会自动拆分 Proposal。'],
      ['撤回和恢复', '采纳后发现不对，可以从正文版本记录恢复上一版。恢复不会删除其他场景的数据。']
    ]},
    { id: 'proposal-review', category: 'write', title: 'Proposal 审查', summary: '逐张确认 Agent 的建议，最后再生成发布版本。', status: '可用', sections: [
      ['先看什么', '先处理标成“阻塞”的问题，再看表情、动作、背景和音效建议。阻塞问题不解决，不能编译。'],
      ['卡片上的操作', '可以编辑、插入台词、插入演出、移动、删除或重新绑定角色。每次操作都会保留当前草稿版本。'],
      ['为什么要人工确认', '模型可能理解错角色、语气或时间顺序。审查页是最后一道检查，不要把生成结果直接当成定稿。'],
      ['审查完成后', '点“检查问题”，确认没有待处理项，再编译 ScriptRelease。']
    ]},
    { id: 'ai', category: 'write', title: 'AI 和 Agent', summary: '知道模型会做什么，也知道它不会做什么。', status: '需要本机配置', sections: [
      ['Fake Provider 和真实模型', 'Fake Provider 只用于测试界面和接口。真实模型需要地址、模型名和 API Key，并先点“测试文字”。'],
      ['Agent 可以做什么', 'Agent 可以根据当前场景、人物卡和已确认资料提出演出建议，也可以生成审查项。'],
      ['Agent 不会做什么', 'Agent 不会直接发布正文，不会绕过人工审查修改 ScriptRelease，也不会替你决定最终演出。'],
      ['失败时怎么办', '超时、429 或 5xx 通常可以重试。改过模型配置后，旧任务需要按当前配置重新开始。']
    ]},
    { id: 'production', category: 'produce', title: 'AA 制作', summary: '把确认过的 ScriptRelease 变成 AA 工程。', status: '可用', sections: [
      ['开始前', '先连接自己的 AzureArchive 工作区。HaloCue 只读取资源索引，不会把资源复制进公开包。'],
      ['制作顺序', '创建制作任务，绑定角色，处理背景和音效请求，再逐卡审查。'],
      ['编译和安装', '点“检查问题”，解决所有阻塞项后再编译。安装前确认分类和剧情名称。'],
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
