(function (exports) {
  'use strict';

  function value(documentRef, selector) {
    return documentRef.querySelector(selector);
  }

  function positiveInteger(input) {
    const parsed = Number(input);
    return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : null;
  }

  function nextOutputLimitState(current, capability, options) {
    current = current || {};
    capability = capability || {};
    options = options || {};
    const recommended = positiveInteger(capability.max_output_tokens);
    const recommendationLabel = capability.source_label || '上限未识别';
    if (!recommended) {
      return Object.assign({}, current, {
        source: current.source === 'manual' ? 'manual' : 'unknown',
        recommended: null,
        recommendationSource: 'unknown',
        recommendationLabel: recommendationLabel
      });
    }
    if (current.source === 'manual' && !options.modelChanged) {
      return Object.assign({}, current, {
        recommended: recommended,
        recommendationSource: capability.source || 'unknown',
        recommendationLabel: recommendationLabel
      });
    }
    return {
      value: recommended,
      source: capability.source || 'unknown',
      recommended: recommended,
      recommendationSource: capability.source || 'unknown',
      recommendationLabel: recommendationLabel
    };
  }

  function restoreOutputLimitState(current) {
    current = current || {};
    const recommended = positiveInteger(current.recommended);
    if (!recommended) return Object.assign({}, current);
    return {
      value: recommended,
      source: current.recommendationSource || 'unknown',
      recommended: recommended,
      recommendationSource: current.recommendationSource || 'unknown',
      recommendationLabel: current.recommendationLabel || '上限未识别'
    };
  }

  function reasoningOptions(capability) {
    capability = capability || {};
    const options = [];
    const efforts = Array.isArray(capability.efforts) ? capability.efforts : [];
    if (capability.toggle) options.push(['speed', '速度（关闭思考）']);
    if (efforts.indexOf('minimal') >= 0) options.push(['minimal', '最低（开启思考）']);
    if (efforts.indexOf('low') >= 0) options.push(['low', '低（开启思考）']);
    if (efforts.indexOf('medium') >= 0) options.push(['balanced', '均衡（开启思考）']);
    if (efforts.indexOf('high') >= 0) options.push(['deep', '深入（开启思考）']);
    if (efforts.indexOf('xhigh') >= 0) options.push(['xhigh', '更深（开启思考）']);
    if (efforts.indexOf('max') >= 0) options.push(['max', '最大（开启思考）']);
    return options.length ? options : [['provider_default', '供应商默认']];
  }

  function reasoningModeIndex(mode, options) {
    options = Array.isArray(options) && options.length ? options : [['provider_default', '供应商默认']];
    const wanted = String(mode || '').trim();
    const exact = options.findIndex(function (entry) { return entry[0] === wanted; });
    if (exact >= 0) return exact;
    const balanced = options.findIndex(function (entry) { return entry[0] === 'balanced'; });
    if (balanced >= 0) return balanced;
    const thinking = options.findIndex(function (entry) { return entry[0] !== 'speed'; });
    return thinking >= 0 ? thinking : 0;
  }

  function reasoningModeFromControl(control) {
    control = control || {};
    const modes = String(control.dataset && control.dataset.modes || '').split('|').filter(Boolean);
    if (!modes.length) return String(control.value || 'provider_default');
    const index = Math.max(0, Math.min(modes.length - 1, Number(control.value) || 0));
    return modes[index] || modes[0];
  }

  function profilePayload(documentRef) {
    const maxInput = value(documentRef, '#modelMaxTokens');
    const payload = {
      id: value(documentRef, '#modelProfileId').value.trim(),
      name: value(documentRef, '#modelProfileName').value.trim(),
      provider: value(documentRef, '#modelProvider').value,
      service_preset: value(documentRef, '#modelServicePreset') ? value(documentRef, '#modelServicePreset').value : 'custom',
      base_url: value(documentRef, '#modelBaseUrl').value.trim(),
      model: value(documentRef, '#modelName').value.trim(),
      max_tokens: Number(maxInput.value || 16000),
      max_tokens_source: maxInput.dataset.source || 'legacy',
      recommended_max_tokens: positiveInteger(maxInput.dataset.recommended),
      recommended_source: maxInput.dataset.recommendationSource || 'unknown',
      recommended_label: maxInput.dataset.recommendationLabel || '上限未识别',
      vision: Boolean(value(documentRef, '#modelVision').checked),
      api_key: value(documentRef, '#modelApiKey').value
    };
    const reasoning = value(documentRef, '#modelReasoningMode');
    if (reasoning && (reasoning.value || (reasoning.dataset && reasoning.dataset.modes))) payload.reasoning_mode = reasoningModeFromControl(reasoning);
    const contextInput = value(documentRef, '#modelContextWindowTokens');
    const contextSource = value(documentRef, '#modelContextWindowSource');
    const contextTokens = positiveInteger(contextInput && contextInput.value);
    const contextOrigin = contextSource && contextSource.value || 'unknown';
    if (contextTokens) {
      payload.context_window_tokens = contextTokens;
      payload.context_window_source = contextOrigin;
    }
    return payload;
  }

  function newProfileDraft() {
    return {id: '', name: '新模型配置', provider: 'openai', service_preset: 'custom', base_url: '', model: '', max_tokens: 16000, max_tokens_source: 'legacy', recommended_max_tokens: null, recommended_source: 'unknown', recommended_label: '上限未识别', reasoning_mode: 'balanced', context_window_tokens: null, context_window_source: 'unknown', vision: true, api_key: ''};
  }

  function preferredDiscoveredModel(currentModel, models) {
    const current = String(currentModel || '').trim();
    if (current) return current;
    const first = (models || []).find(function (model) {
      return String(model && (model.model_id || model.id) || '').trim();
    });
    return first ? String(first.model_id || first.id).trim() : '';
  }

  function profileChanged(before, after) {
    if (!before || !after) return Boolean(before || after);
    if (String(after.api_key || '').trim()) return true;
      return ['name', 'provider', 'service_preset', 'base_url', 'model', 'max_tokens', 'max_tokens_source', 'recommended_max_tokens', 'recommended_source', 'recommended_label', 'reasoning_mode', 'context_window_tokens', 'context_window_source', 'vision'].some(function (field) {
      return String(before[field] == null ? '' : before[field]) !== String(after[field] == null ? '' : after[field]);
    });
  }

  function statusLabel(role, status) {
    const kind = role === 'vision' ? '图片' : '文字';
    if (status === 'passed') return kind + '已通过';
    if (status === 'failed') return kind + '测试失败';
    if (status === 'unsupported') return '不支持' + kind;
    return kind + '未测试';
  }

  function assignmentSecretStatus(payload) {
    payload = payload || {};
    const assignments = payload.assignments || {};
    const models = Array.isArray(payload.models) ? payload.models : [];
    const connections = Array.isArray(payload.connections) ? payload.connections : [];
    const byModelId = function (id) { return models.find(function (model) { return model.id === id; }); };
    const required = [];
    const base = byModelId(assignments.base_model_id);
    if (!base) return 'missing';
    required.push(base);
    if (assignments.vision_mode === 'separate') {
      const vision = byModelId(assignments.vision_model_id);
      if (!vision) return 'missing';
      required.push(vision);
    }
    return required.every(function (model) {
      const connection = connections.find(function (item) { return item.id === model.connection_id; });
      return connection && connection.secret_status === 'saved';
    }) ? 'saved' : 'missing';
  }

  function modelDeleteControl(assigned, compatibilityMode) {
    if (compatibilityMode) {
      return {disabled: true, title: '重新启动程序后可删除模型'};
    }
    if (assigned) {
      return {disabled: false, title: '当前模型正在使用，点击查看说明'};
    }
    return {disabled: false, title: '删除模型'};
  }

  function modelReadinessLabel(model) {
    model = model || {};
    if (!model.configured) return '仅转换格式时无需 AI';
    const base = [model.name, model.model].filter(Boolean).join(' · ');
    if (!model.vision_model) return base;
    const sameModel = model.name === model.vision_name && model.model === model.vision_model;
    const vision = sameModel
      ? '图片：同基础模型'
      : '图片：' + [model.vision_name, model.vision_model].filter(Boolean).join(' · ');
    return base + '；' + vision;
  }

  function connectionDisplayName(connection, presets) {
    connection = connection || {};
    const name = String(connection.name || '').trim();
    const key = String(connection.service_preset || 'custom');
    let preset = null;
    if (Array.isArray(presets)) preset = presets.find(function (item) { return item.key === key; });
    else if (presets && typeof presets === 'object') preset = presets[key];
    const label = String(preset && preset.label || '').trim();
    if (!label || name.toLowerCase().indexOf(label.toLowerCase()) >= 0) return name || label;
    return label + ' · ' + name;
  }

  function filterModels(models, role, query, provider, status) {
    const needle = String(query || '').trim().toLowerCase();
    return (Array.isArray(models) ? models : []).filter(function (model) {
      const capability = role === 'vision' ? model.vision_status : model.text_status;
      if (role && capability === 'unsupported') return false;
      if (status && capability !== status) return false;
      if (provider && String(model.connection_id || model.connection_name || model.provider || '') !== String(provider)) return false;
      if (!needle) return true;
      return [model.model, model.connection_name, model.provider].some(function (value) {
        return String(value || '').toLowerCase().indexOf(needle) >= 0;
      });
    });
  }

  function reasoningCapability(model, servicePreset) {
    model = String(model || '').trim();
    servicePreset = String(servicePreset || 'custom').trim().toLowerCase();
    if (servicePreset === 'deepseek' && /^deepseek-v4-flash(?:-\d+)?$/.test(model)) {
      return {toggle: true, efforts: ['low', 'medium', 'high'], default_mode: 'balanced', wire_protocol: 'deepseek_thinking', source: 'catalog'};
    }
    return {toggle: false, efforts: [], default_mode: 'provider_default', wire_protocol: 'none', source: 'unknown'};
  }

  function nextReasoningCapability(_current, profile) {
    profile = profile || {};
    return reasoningCapability(profile.model, profile.service_preset);
  }

  function legacyWorkbench(payload) {
    payload = payload || {};
    const profiles = Array.isArray(payload.profiles) ? payload.profiles : [];
    const connections = profiles.map(function (profile) {
      return {
        id: 'legacy-connection-' + profile.id,
        name: profile.name,
        service_preset: profile.service_preset || 'custom',
        protocol: profile.provider || 'openai',
        base_url: profile.base_url || '',
        secret_status: profile.secret_status || 'missing'
      };
    });
    const models = profiles.map(function (profile) {
      return {
        id: 'legacy-model-' + profile.id,
        legacy_profile_id: profile.id,
        connection_id: 'legacy-connection-' + profile.id,
        connection_name: profile.name,
        provider: profile.provider || 'openai',
        model: profile.model,
        max_tokens: Number(profile.max_tokens || 16000),
        text_status: 'untested',
        vision_status: profile.vision === false ? 'unsupported' : 'untested'
      };
    });
    const active = models.find(function (model) {
      return model.legacy_profile_id === payload.active_profile_id;
    });
    return {
      schema_version: 1,
      compatibility_mode: 'legacy',
      connections: connections,
      models: models,
      assignments: {
        base_model_id: active ? active.id : (models[0] || {}).id || '',
        vision_mode: 'disabled',
        vision_model_id: ''
      },
      presets: payload.presets || {}
    };
  }

  exports.ModelSettings = {
    profilePayload: profilePayload,
    nextOutputLimitState: nextOutputLimitState,
    restoreOutputLimitState: restoreOutputLimitState,
    newProfileDraft: newProfileDraft,
    preferredDiscoveredModel: preferredDiscoveredModel,
    profileChanged: profileChanged,
    statusLabel: statusLabel,
    assignmentSecretStatus: assignmentSecretStatus,
    modelDeleteControl: modelDeleteControl,
    modelReadinessLabel: modelReadinessLabel,
    connectionDisplayName: connectionDisplayName,
    filterModels: filterModels,
    reasoningCapability: reasoningCapability,
    nextReasoningCapability: nextReasoningCapability,
    reasoningOptions: reasoningOptions,
    reasoningModeIndex: reasoningModeIndex,
    reasoningModeFromControl: reasoningModeFromControl,
    legacyWorkbench: legacyWorkbench
  };
})(window);
