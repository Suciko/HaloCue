(function (exports) {
  'use strict';

  async function request(path, options) {
    const response = await fetch(path, options);
    const contentType = response.headers.get('content-type') || '';
    const body = contentType.includes('application/json') ? await response.json() : {};
    if (!response.ok) {
      throw Object.assign(new Error(body.e || '请求失败'), body, {status: response.status});
    }
    return body;
  }

  function json(method, payload) {
    return {method: method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload || {})};
  }

  function poll(path, done, options) {
    options = options || {}; const baseDelay = options.interval || 800; const isCurrent = options.isCurrent || function () { return true; }; const retryOn = options.retryOn || function (error) { return !error.status || error.status >= 500; };
    function wait(ms) { return new Promise(function (resolve) { setTimeout(resolve, ms); }); }
    function check(attempt) {
      if (!isCurrent()) return Promise.resolve(null);
      return request(path).then(function (value) {
        if (options.onProgress) options.onProgress(value);
        if (!isCurrent() || done(value)) return value;
        return wait(baseDelay).then(function () { return check(0); });
      }).catch(function (error) {
        if (!isCurrent()) return null;
        if (!retryOn(error)) throw error;
        if (options.onRetry) options.onRetry(error, attempt);
        return wait(Math.min(8000, baseDelay * Math.pow(2, attempt))).then(function () { return check(attempt + 1); });
      });
    }
    return check(0);
  }

  exports.Api = {request: request, json: json, poll: poll};
})(window);
