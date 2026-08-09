/* 复制到当前剧情的任务控制器，公开四个稳定进度阶段。 */
(function (exports) {
  'use strict';

  function TransferController(workbench) {
    this.workbench = workbench;
    this.state = 'idle';
    this.item = null;
  }

  TransferController.prototype.setState = function (state, options) {
    this.state = state;
    if (this.workbench && this.workbench.setTransferState) {
      this.workbench.setTransferState(state, options || {});
    }
  };

  TransferController.prototype.copy = async function (item) {
    const storyToken = String(this.workbench.context.story_token || '');
    const source = item && Array.isArray(item.copies) ? item.copies[0] : null;
    if (!item || !storyToken || !source || !source.copy_token) {
      this.setState('无法复制', {retry: true, message: '刷新素材工作台后重新选择素材。'});
      throw new Error('缺少复制所需的安全标识');
    }
    this.item = item;
    this.setState('正在校验');
    try {
      this.setState('正在复制');
      const result = await exports.Api.request(
        '/api/assets/library/copy-to-story',
        exports.Api.json('POST', {
          story_token: storyToken,
          kind: item.kind,
          aa_key: item.aa_key,
          sha256: item.sha256,
          source_copy_token: source.copy_token
        })
      );
      this.setState('正在登记');
      item.registered_in_current = true;
      if (this.workbench.refresh) await this.workbench.refresh();
      this.setState('本章已登记');
      const detail = {
        story_token: storyToken,
        kind: item.kind,
        aa_key: item.aa_key,
        state: result.state,
        asset: result.asset,
        context: Object.assign({}, this.workbench.context)
      };
      if (exports.dispatchEvent && typeof CustomEvent === 'function') {
        exports.dispatchEvent(new CustomEvent('assetworkbench:copied', {detail: detail}));
      }
      return result;
    } catch (error) {
      const action = String(error.action || '检查网络与当前剧情后在原位置重试。');
      this.setState('复制未完成', {retry: true, message: action});
      throw error;
    }
  };

  exports.StoryUI = exports.StoryUI || {};
  exports.StoryUI.TransferController = TransferController;
})(window);
