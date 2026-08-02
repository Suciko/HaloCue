/* 单章节副本描述、确认和移除控制器。 */
(function (exports) {
  'use strict';

  function CopyManager(workbench) {
    this.workbench = workbench;
    this.item = null;
  }

  CopyManager.prototype.open = async function (item) {
    this.item = item || null;
    return this.item;
  };

  exports.StoryUI = exports.StoryUI || {};
  exports.StoryUI.CopyManager = CopyManager;
})(window);
