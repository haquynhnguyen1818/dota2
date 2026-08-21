function setupCombo({ comboId, triggerId, panelId, listId, clearId, valueId, searchId, options, getValue, onSelect, onClear }) {
  const combo = document.getElementById(comboId);
  const trigger = document.getElementById(triggerId);
  const list = document.getElementById(listId);
  const clearBtn = clearId ? document.getElementById(clearId) : null;
  const searchEl = searchId ? document.getElementById(searchId) : null;

  function currentOptions() {
    return typeof options === "function" ? options() : options;
  }

  function renderOptions(filter) {
    const q = (filter || "").toLowerCase();
    const filtered = currentOptions().filter((o) => o.toLowerCase().includes(q));
    if (filtered.length === 0) {
      list.innerHTML = '<div class="combo-empty">No matches</div>';
      return;
    }
    list.innerHTML = filtered
      .map((o) => {
        const active = o === getValue() ? "active" : "";
        return `<div class="combo-option ${active}" role="option" data-value="${o}">${o}</div>`;
      })
      .join("");
  }

  function open() {
    combo.classList.add("open");
    trigger.setAttribute("aria-expanded", "true");
    renderOptions(searchEl ? searchEl.value : "");
    if (searchEl) {
      searchEl.value = "";
      setTimeout(() => searchEl.focus(), 10);
    }
  }
  function close() {
    combo.classList.remove("open");
    trigger.setAttribute("aria-expanded", "false");
  }
  function toggle() {
    combo.classList.contains("open") ? close() : open();
  }

  trigger.addEventListener("click", toggle);
  trigger.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      toggle();
    }
  });

  list.addEventListener("click", (e) => {
    const opt = e.target.closest(".combo-option");
    if (!opt) return;
    onSelect(opt.dataset.value);
    close();
  });

  if (searchEl) {
    searchEl.addEventListener("input", () => renderOptions(searchEl.value));
    searchEl.addEventListener("click", (e) => e.stopPropagation());
  }

  if (clearBtn) {
    clearBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      onClear();
      close();
    });
  }

  document.addEventListener("click", (e) => {
    if (!combo.contains(e.target)) close();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") close();
  });
}
