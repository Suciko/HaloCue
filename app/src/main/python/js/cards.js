/**
 * AA 剧本编译器 - 卡片视图组件 (cards.js)
 * 安全地使用 DOM API 与 textContent 渲染只读卡片，无内联事件与样式。
 */
(function (exports) {
  'use strict';

  function createCardElement(card, options) {
    options = options || {};
    const cardEl = document.createElement('div');
    cardEl.className = 'card-item card-kind-' + (card.kind || 'line');
    cardEl.dataset.cardId = card.card_id;

    if (card.review_state === 'pending') {
      cardEl.classList.add('card-pending');
    }

    // 1. 行号徽章
    const lineBadge = document.createElement('span');
    lineBadge.className = 'card-line-no';
    lineBadge.textContent = '#' + card.line_no;
    cardEl.appendChild(lineBadge);

    // 2. 类型图标
    if (card.kind === 'background_request') {
      const bgIcon = document.createElement('span');
      bgIcon.className = 'card-kind-badge bg-request-badge';
      bgIcon.textContent = '📌 背景请求: ' + (card.current.description || '');
      cardEl.appendChild(bgIcon);
    } else if (card.kind === 'scene') {
      const sceneBadge = document.createElement('span');
      sceneBadge.className = 'card-kind-badge scene-badge';
      sceneBadge.textContent = '## 场景: ' + (card.current.title || '');
      cardEl.appendChild(sceneBadge);
    } else if (card.kind === 'separator') {
      const separatorBadge = document.createElement('span');
      separatorBadge.className = 'card-kind-badge separator-badge';
      separatorBadge.textContent = '场景分隔';
      cardEl.appendChild(separatorBadge);
    }

    // 3. 台词 / 指令主体
    const contentEl = document.createElement('div');
    contentEl.className = 'card-body';

    if (card.kind === 'line') {
      const whoEl = document.createElement('strong');
      whoEl.className = 'card-who';
      whoEl.textContent = (card.current.who || '') + ': ';
      contentEl.appendChild(whoEl);

      const textEl = document.createElement('span');
      textEl.className = 'card-text';
      textEl.textContent = card.current.text || '';
      contentEl.appendChild(textEl);
    } else if (card.kind === 'dir') {
      const dirEl = document.createElement('span');
      dirEl.className = 'card-dir';
      dirEl.textContent = '@' + (card.current.cmd || '') + ' ' + (card.current.arg || '');
      contentEl.appendChild(dirEl);
    } else if (
      card.kind !== 'background_request' &&
      card.kind !== 'scene' &&
      card.kind !== 'separator'
    ) {
      const rawEl = document.createElement('span');
      rawEl.className = 'card-raw';
      rawEl.textContent = card.raw || '';
      contentEl.appendChild(rawEl);
    }
    cardEl.appendChild(contentEl);

    // 4. 参数 Chips
    if (card.current && (card.current.face || card.current.emo || card.current.act || card.current.fx)) {
      const chipsEl = document.createElement('div');
      chipsEl.className = 'card-chips';
      ['face', 'emo', 'act', 'fx'].forEach(function (key) {
        if (card.current[key]) {
          const chip = document.createElement('span');
          chip.className = 'card-chip chip-' + key;
          chip.textContent = key + ':' + card.current[key];
          chipsEl.appendChild(chip);
        }
      });
      cardEl.appendChild(chipsEl);
    }

    // 4b. 背景请求卡动作
    if (card.kind === 'background_request' && (options.onUseDefaultBackground || options.onChooseBackground || options.onFillBackground)) {
      const actionsEl = document.createElement('div');
      actionsEl.className = 'card-actions';
      function appendAction(label, callback) {
        if (!callback) return;
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'ghost card-fill-bg';
        button.textContent = label;
        button.addEventListener('click', function (event) {
          event.stopPropagation();
          callback(card, button);
        });
        actionsEl.appendChild(button);
      }
      appendAction('使用默认黑屏', options.onUseDefaultBackground);
      appendAction('选择官方背景', options.onChooseBackground);
      appendAction('从历史项目复制', options.onFillBackground);
      cardEl.appendChild(actionsEl);
    }

    // 5. 点击卡片事件
    cardEl.addEventListener('click', function () {
      if (options.onSelectCard) {
        options.onSelectCard(card);
      }
    });

    return cardEl;
  }

  function renderCardList(container, cardsData, options) {
    container.textContent = '';
    if (!cardsData || cardsData.length === 0) {
      const emptyEl = document.createElement('div');
      emptyEl.className = 'card-list-empty';
      emptyEl.textContent = '暂无卡片';
      container.appendChild(emptyEl);
      return;
    }

    const fragment = document.createDocumentFragment();
    cardsData.forEach(function (card) {
      fragment.appendChild(createCardElement(card, options));
    });
    container.appendChild(fragment);
  }

  exports.CardList = {
    renderCardList: renderCardList,
    createCardElement: createCardElement
  };
})(window);
