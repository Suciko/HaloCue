(() => {
  "use strict";

  const toast = document.querySelector("#toast");
  const pendingCount = document.querySelector("#pending-count");
  const sourcePopover = document.querySelector("#source-popover");
  let toastTimer = null;

  const showToast = (message) => {
    toast.textContent = message;
    toast.classList.add("show");
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => toast.classList.remove("show"), 2600);
  };

  const setExpanded = (button, panel) => {
    const willExpand = button.getAttribute("aria-expanded") !== "true";
    button.setAttribute("aria-expanded", String(willExpand));
    panel.hidden = !willExpand;
    const label = button.querySelector(".toggle-label");
    if (label) label.textContent = willExpand ? "收起详情" : "技术详情";
  };

  document.querySelectorAll("[aria-controls]").forEach((button) => {
    const panel = document.getElementById(button.getAttribute("aria-controls"));
    if (!panel) return;
    button.addEventListener("click", () => setExpanded(button, panel));
  });

  const updatePendingCount = () => {
    const pending = document.querySelectorAll(".proposal-card:not([data-state])").length;
    pendingCount.textContent = String(pending);
    pendingCount.nextElementSibling.innerHTML = pending === 0 ? "项提案<br>已经处理" : "项提案<br>等待确认";
  };

  const updateSelection = (card) => {
    if (!card || card.dataset.state) return;
    const checkboxes = [...card.querySelectorAll('input[type="checkbox"]')];
    const selected = checkboxes.filter((checkbox) => checkbox.checked).length;
    const total = checkboxes.length;
    const count = card.querySelector("[data-selected-count]");
    const apply = card.querySelector('[data-decision="apply"]');
    const selectAll = card.querySelector("[data-select-all]");
    if (count) count.textContent = `已选择 ${selected} / ${total}`;
    if (apply) {
      apply.textContent = `应用 ${selected} 项修改`;
      apply.disabled = selected === 0;
    }
    if (selectAll) selectAll.textContent = selected === total ? "取消全选" : "全部选择";
  };

  const applyDecision = (card, decision) => {
    if (card.dataset.state) return;

    const checkboxes = [...card.querySelectorAll('input[type="checkbox"]')];
    const selected = checkboxes.filter((checkbox) => checkbox.checked);
    const status = card.querySelector(".proposal-status");
    const note = card.querySelector(".decision-note");
    const isWorld = card.dataset.proposal === "world";

    if (decision === "apply" && selected.length === 0) {
      showToast("请至少勾选一个字段后再应用。");
      return;
    }

    const stateMap = {
      apply: { state: selected.length === checkboxes.length ? "accepted" : "partial", label: "应用预览", note: `原型预览：正式接入后会应用选中的 ${selected.length} 个字段，并生成新的资料修订。` },
      reject: { state: "rejected", label: "驳回预览", note: "原型预览：正式接入后会退回 Proposal，不改变正式资料。" }
    };
    const result = stateMap[decision];

    card.dataset.state = result.state;
    status.className = `proposal-status status-${result.state}`;
    status.textContent = result.label;
    note.textContent = result.note;

    checkboxes.forEach((checkbox) => {
      const row = checkbox.closest(".field-row, label");
      const rowStatus = row?.querySelector(".row-status");
      checkbox.disabled = true;
      if (!rowStatus) return;
      if (decision === "reject") {
        rowStatus.textContent = "未采用";
        rowStatus.style.color = "var(--red)";
      } else if (decision === "apply" && checkbox.checked) {
        checkbox.checked = true;
        rowStatus.textContent = "已应用";
        rowStatus.style.color = "var(--green)";
      } else {
        rowStatus.textContent = "已跳过";
        rowStatus.style.color = "var(--muted)";
      }
    });

    updatePendingCount();
    showToast(result.note);
  };

  document.querySelectorAll("[data-decision]").forEach((button) => {
    button.addEventListener("click", () => applyDecision(button.closest(".proposal-card"), button.dataset.decision));
  });

  document.querySelectorAll(".proposal-card").forEach((card) => {
    card.querySelectorAll('input[type="checkbox"]').forEach((checkbox) => {
      checkbox.addEventListener("change", () => updateSelection(card));
    });
    card.querySelector("[data-select-all]")?.addEventListener("click", () => {
      const checkboxes = [...card.querySelectorAll('input[type="checkbox"]')];
      const shouldSelect = checkboxes.some((checkbox) => !checkbox.checked);
      checkboxes.forEach((checkbox) => { checkbox.checked = shouldSelect; });
      updateSelection(card);
    });
    updateSelection(card);
  });

  const positionPopover = (anchor) => {
    const rect = anchor.getBoundingClientRect();
    const width = Math.min(360, window.innerWidth - 28);
    let left = rect.left;
    if (left + width > window.innerWidth - 14) left = window.innerWidth - width - 14;
    const top = Math.min(rect.bottom + 8, window.innerHeight - 220);
    sourcePopover.style.left = `${Math.max(14, left)}px`;
    sourcePopover.style.top = `${Math.max(14, top)}px`;
  };

  document.querySelectorAll(".source-link").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      sourcePopover.querySelector("h2").textContent = button.dataset.source;
      sourcePopover.hidden = false;
      positionPopover(button);
    });
  });

  const closePopover = () => { sourcePopover.hidden = true; };
  sourcePopover.querySelector(".popover-close").addEventListener("click", closePopover);
  document.addEventListener("click", (event) => {
    if (!sourcePopover.hidden && !sourcePopover.contains(event.target)) closePopover();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closePopover();
  });
  window.addEventListener("resize", closePopover);
})();
