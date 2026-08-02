(function (exports) {
  'use strict';

  function value(documentRef, selector) {
    return documentRef.querySelector(selector);
  }

  function profilePayload(documentRef) {
    return {
      id: value(documentRef, '#modelProfileId').value.trim(),
      name: value(documentRef, '#modelProfileName').value.trim(),
      provider: value(documentRef, '#modelProvider').value,
      base_url: value(documentRef, '#modelBaseUrl').value.trim(),
      model: value(documentRef, '#modelName').value.trim(),
      max_tokens: Number(value(documentRef, '#modelMaxTokens').value || 16000),
      vision: Boolean(value(documentRef, '#modelVision').checked),
      api_key: value(documentRef, '#modelApiKey').value,
      save_key: Boolean(value(documentRef, '#modelSaveKey').checked)
    };
  }

  exports.ModelSettings = {profilePayload: profilePayload};
})(window);
