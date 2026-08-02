/* 复制到当前剧情的任务控制器；目录只消费它公开的稳定状态。 */
(function (exports) {
  'use strict';

  function TransferController(workbench) {
    this.workbench = workbench;
    this.state = 'idle';
  }

  TransferController.prototype.copy = async function () {
    throw new Error('复制控制器尚未收到素材');
  };

  exports.StoryUI = exports.StoryUI || {};
  exports.StoryUI.TransferController = TransferController;
})(window);
