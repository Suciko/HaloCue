(function () {
  "use strict";

  // Stable capability IDs stay renderer-agnostic. This adapter only exposes
  // presentation state; a local manifest can replace the mapping later.
  const MOTION_CLASSES = Object.freeze({
    "motion/nod": "is-motion-nod",
    "motion/appear": "is-motion-appear",
  });

  const EMOTICONS = Object.freeze({
    "emoticon/bulb": Object.freeze({ symbol: "✦", label: "灵光" }),
    "emoticon/ellipsis": Object.freeze({ symbol: "…", label: "省略" }),
    "emoticon/steam": Object.freeze({ symbol: "〰", label: "蒸汽" }),
  });

  function stateId(value) {
    return typeof value === "string" && value.trim() ? value.trim() : "";
  }

  function motionClass(value) {
    return MOTION_CLASSES[stateId(value)] || "";
  }

  function emoticon(value) {
    const id = stateId(value);
    return EMOTICONS[id] ? { id, ...EMOTICONS[id] } : null;
  }

  window.HaloCueCapabilityRuntime = Object.freeze({
    motionClass,
    emoticon,
    stateId,
  });
}());
