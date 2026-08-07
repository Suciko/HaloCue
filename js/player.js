/**
 * AA 剧本编译器 - 伪演出预览播放器 (player.js)
 * 安全使用 DOM API 和 textContent，按卡片顺序与 card_id 联动定位与播放。
 */
(function (exports) {
  'use strict';

  function Player(container, options) {
    this.container = container;
    this.options = options || {};
    this.cards = [];
    this.sceneStates = [];
    this.currentIndex = 0;
    this.isPlaying = false;
    this.timer = null;

    this._initUI();
  }

  Player.prototype._initUI = function () {
    this.container.textContent = '';

    const root = document.createElement('div');
    root.className = 'pseudo-player';

    // 屏幕呈现区
    const stage = document.createElement('div');
    stage.className = 'player-stage';

    const bgLayer = document.createElement('div');
    bgLayer.className = 'player-bg-layer';
    stage.appendChild(bgLayer);

    const progressEl = document.createElement('div');
    progressEl.className = 'player-progress';
    stage.appendChild(progressEl);

    const dialogBox = document.createElement('div');
    dialogBox.className = 'player-dialog-box';

    const speakerName = document.createElement('div');
    speakerName.className = 'player-speaker-name';
    dialogBox.appendChild(speakerName);

    const dialogText = document.createElement('div');
    dialogText.className = 'player-dialog-text';
    dialogBox.appendChild(dialogText);

    stage.appendChild(dialogBox);
    root.appendChild(stage);

    // 控制栏
    const controls = document.createElement('div');
    controls.className = 'player-controls';

    const prevBtn = document.createElement('button');
    prevBtn.className = 'player-btn player-btn-prev';
    prevBtn.textContent = '◀ 上一行';
    const self = this;
    prevBtn.addEventListener('click', function () {
      self.prev();
    });
    controls.appendChild(prevBtn);

    const playBtn = document.createElement('button');
    playBtn.className = 'player-btn player-btn-toggle';
    playBtn.textContent = '播放';
    playBtn.addEventListener('click', function () {
      self.togglePlay();
    });
    controls.appendChild(playBtn);

    const nextBtn = document.createElement('button');
    nextBtn.className = 'player-btn player-btn-next';
    nextBtn.textContent = '下一行 ▶';
    nextBtn.addEventListener('click', function () {
      self.next();
    });
    controls.appendChild(nextBtn);

    root.appendChild(controls);
    this.container.appendChild(root);

    this.speakerNameEl = speakerName;
    this.dialogTextEl = dialogText;
    this.bgLayerEl = bgLayer;
    this.progressEl = progressEl;
    this.playBtnEl = playBtn;
  };

  Player.prototype.loadCards = function (cards) {
    this.cards = cards || [];
    let background = '';
    this.sceneStates = this.cards.map(function (card) {
      const current = card && card.current || {};
      const command = card && card.kind === 'dir' ? String(current.cmd || '').toLowerCase() : '';
      if (command === 'bg' || command === 'scene') background = String(current.arg || '');
      return {background: background};
    });
    this.currentIndex = 0;
    this.renderCurrent();
  };

  Player.prototype.jumpToCard = function (cardId) {
    for (let i = 0; i < this.cards.length; i++) {
      if (this.cards[i].card_id === cardId) {
        this.currentIndex = i;
        this.renderCurrent();
        break;
      }
    }
  };

  Player.prototype.renderCurrent = function () {
    this.bgLayerEl.style.backgroundImage = '';
    this.bgLayerEl.classList.remove('has-bg');
    if (this.progressEl) this.progressEl.textContent = this.cards && this.cards.length ? ((this.currentIndex + 1) + ' / ' + this.cards.length) : '';

    if (!this.cards || this.cards.length === 0) {
      this.speakerNameEl.textContent = '';
      this.dialogTextEl.textContent = '选择卡片，在这里预览这句演出';
      return;
    }

    const card = this.cards[this.currentIndex];
    if (!card) return;
    const sceneState = this.sceneStates[this.currentIndex] || {};
    if (sceneState.background) {
      this.bgLayerEl.style.backgroundImage = 'url("/thumb/bg/' + encodeURIComponent(sceneState.background) + '")';
      this.bgLayerEl.classList.add('has-bg');
    }

    if (card.kind === 'line') {
      this.speakerNameEl.textContent = card.current.who || '（旁白）';
      this.dialogTextEl.textContent = card.current.text || '';
    } else if (card.kind === 'dir' && (card.current.cmd === 'bg' || card.current.cmd === 'scene')) {
      const name = card.current.arg || '';
      this.speakerNameEl.textContent = card.current.cmd === 'scene' ? '【场景】' : '【背景】';
      this.dialogTextEl.textContent = name || card.raw || '';
    } else if (card.kind === 'dir' && card.current.cmd === 'trans') {
      this.speakerNameEl.textContent = '【转场】';
      this.dialogTextEl.textContent = card.current.arg || card.raw || '';
    } else if (card.kind === 'dir' && card.current.cmd === 'place') {
      this.speakerNameEl.textContent = '【地点】';
      this.dialogTextEl.textContent = card.current.arg || card.raw || '';
    } else if (card.kind === 'scene') {
      this.speakerNameEl.textContent = '【场景切换】';
      this.dialogTextEl.textContent = card.current.title || '';
    } else if (card.kind === 'background_request') {
      this.speakerNameEl.textContent = '【背景请求】';
      this.dialogTextEl.textContent = '📌 ' + (card.current.description || '');
    } else {
      this.speakerNameEl.textContent = '【指令/文本】';
      this.dialogTextEl.textContent = card.raw || '';
    }

    if (this.options.onCardChange) {
      this.options.onCardChange(card, this.currentIndex);
    }
  };

  Player.prototype.next = function () {
    if (this.currentIndex < this.cards.length - 1) {
      this.currentIndex++;
      this.renderCurrent();
    } else {
      this.pause();
    }
  };

  Player.prototype.prev = function () {
    if (this.currentIndex > 0) {
      this.currentIndex--;
      this.renderCurrent();
    }
  };

  Player.prototype.togglePlay = function () {
    if (this.isPlaying) {
      this.pause();
    } else {
      this.play();
    }
  };

  Player.prototype.play = function () {
    this.isPlaying = true;
    this.playBtnEl.textContent = '暂停';
    const self = this;
    this.timer = setInterval(function () {
      if (self.currentIndex < self.cards.length - 1) {
        self.next();
      } else {
        self.pause();
      }
    }, 2500);
  };

  Player.prototype.pause = function () {
    this.isPlaying = false;
    this.playBtnEl.textContent = '播放';
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
  };

  exports.Player = Player;
})(window);
