const state = {
  heroes: [],
  nameById: {},
  opponentPicks: [],
  currentRole: "Carry",
  suggestionsByRole: null,
  suggestionsForPicks: null, // the opponent-pick ids state.suggestionsByRole was fetched for
  expanded: {},
};

let requestSeq = 0;

function renderChips() {
  const el = document.getElementById("chips");
  if (state.opponentPicks.length === 0) {
    el.innerHTML = '<span class="chip-empty">No opponent picks yet</span>';
    return;
  }
  el.innerHTML = state.opponentPicks
    .map(
      (id) => `
    <span class="chip">${state.nameById[id]}
      <button aria-label="Remove ${state.nameById[id]}" data-remove="${id}">×</button>
    </span>
  `
    )
    .join("");
  el.querySelectorAll("button[data-remove]").forEach((btn) => {
    btn.addEventListener("click", () => removePick(Number(btn.dataset.remove)));
  });
}

function populateSelect() {
  const sel = document.getElementById("heroSelect");
  const available = state.heroes
    .filter((h) => !state.opponentPicks.includes(h.id))
    .sort((a, b) => a.name.localeCompare(b.name));
  sel.innerHTML =
    '<option value="">Select hero…</option>' + available.map((h) => `<option value="${h.id}">${h.name}</option>`).join("");
  updateAddBtnState();
}

function updateAddBtnState() {
  const sel = document.getElementById("heroSelect");
  document.getElementById("addBtn").disabled = !sel.value || state.opponentPicks.length >= MAX_PICKS;
}

async function onAddPick() {
  const sel = document.getElementById("heroSelect");
  const id = Number(sel.value);
  if (!id) return;
  state.opponentPicks.push(id);
  renderChips();
  populateSelect();
  await refreshSuggestions();
}

async function removePick(id) {
  state.opponentPicks = state.opponentPicks.filter((h) => h !== id);
  renderChips();
  populateSelect();
  await refreshSuggestions();
}

async function onReset() {
  state.opponentPicks = [];
  renderChips();
  populateSelect();
  await refreshSuggestions();
}

async function refreshSuggestions() {
  state.expanded = {};
  const seq = ++requestSeq;
  const picksSnapshot = [...state.opponentPicks];
  if (picksSnapshot.length === 0) {
    state.suggestionsByRole = null;
    state.suggestionsForPicks = null;
    renderLists();
    return;
  }
  const result = await getDraftSuggestions(picksSnapshot);
  if (seq !== requestSeq) return; // a newer request has since superseded this one
  state.suggestionsByRole = {};
  result.roles.forEach((r) => {
    state.suggestionsByRole[r.role] = { best: r.best, worst: r.worst };
  });
  state.suggestionsForPicks = picksSnapshot;
  renderLists();
}

function buildRowsHTML(list, role, kind) {
  const expandKey = `${role}_${kind}`;
  const expandedHeroId = state.expanded[expandKey] ?? null;
  let html = "";
  list.forEach((item, idx) => {
    const sign = item.total_advantage >= 0 ? "pos" : "neg";
    const tier = idx < 3 ? "tier-signal" : "";
    const barPct = Math.min(Math.abs(item.total_advantage * 100) / SCALE_MAX, 1) * 50;
    const wrPct = item.hero_wr * 100;
    const wrClass = wrPct >= 50 ? "wr-good" : "";
    const valueText = (item.total_advantage >= 0 ? "+" : "") + (item.total_advantage * 100).toFixed(2) + "%";
    html += `
      <div class="row ${tier} ${sign} clickable" data-hero-id="${item.hero_id}" data-role="${role}" data-kind="${kind}" style="animation-delay:${idx * 30}ms">
        <div class="row-rank">${String(idx + 1).padStart(2, "0")}</div>
        <div class="row-main">
          <div class="row-name" title="${item.hero_name}">${item.hero_name}</div>
          <div class="row-wr ${wrClass}">WR ${wrPct.toFixed(2)}%</div>
        </div>
        <div class="row-bar-track">
          <div class="row-bar ${sign}" style="width:${barPct}%;"></div>
        </div>
        <div class="row-value ${sign}">${valueText}</div>
      </div>
    `;
    if (item.hero_id === expandedHeroId) {
      item.breakdown.forEach((b) => {
        const bSign = b.advantage >= 0 ? "pos" : "neg";
        const bValueText = (b.advantage >= 0 ? "+" : "") + (b.advantage * 100).toFixed(2) + "%";
        html += `
          <div class="row sub-row ${bSign}">
            <div class="row-rank"></div>
            <div class="row-main">
              <div class="row-name">↳ vs ${b.vs_hero_name}</div>
            </div>
            <div class="row-bar-track"></div>
            <div class="row-value ${bSign}">${bValueText}</div>
          </div>
        `;
      });
    }
  });
  return html;
}

function attachRowHandlers() {
  document.querySelectorAll(".row.clickable").forEach((row) => {
    row.addEventListener("click", () => {
      const heroId = Number(row.dataset.heroId);
      const key = `${row.dataset.role}_${row.dataset.kind}`;
      state.expanded[key] = state.expanded[key] === heroId ? null : heroId;
      renderLists();
    });
  });
}

function renderLists() {
  const bestEl = document.getElementById("bestList");
  const worstEl = document.getElementById("worstList");
  if (!state.suggestionsByRole) {
    bestEl.innerHTML = '<p class="chip-empty">Add an opponent pick to see suggestions.</p>';
    worstEl.innerHTML = "";
    document.getElementById("bestCount").textContent = "";
    document.getElementById("worstCount").textContent = "";
    return;
  }
  const data = state.suggestionsByRole[state.currentRole];
  bestEl.innerHTML = buildRowsHTML(data.best, state.currentRole, "best");
  worstEl.innerHTML = buildRowsHTML(data.worst, state.currentRole, "worst");
  document.getElementById("bestCount").textContent = data.best.length + " heroes";
  document.getElementById("worstCount").textContent = data.worst.length + " heroes";
  attachRowHandlers();
}

function onTabClick(e) {
  const btn = e.target.closest(".tab");
  if (!btn) return;
  document.querySelectorAll(".tab").forEach((t) => {
    t.classList.remove("active");
    t.setAttribute("aria-selected", "false");
  });
  btn.classList.add("active");
  btn.setAttribute("aria-selected", "true");
  state.currentRole = btn.dataset.role;
  renderLists();
}

function onSegClick(e) {
  const btn = e.currentTarget;
  document.querySelectorAll(".seg-btn").forEach((b) => b.classList.remove("active", "pos", "neg"));
  const view = btn.dataset.view;
  btn.classList.add("active", view === "best" ? "pos" : "neg");
  const grid = document.getElementById("listsGrid");
  grid.classList.remove("show-best", "show-worst");
  grid.classList.add(view === "best" ? "show-best" : "show-worst");
}

async function init() {
  state.heroes = await getHeroes();
  state.heroes.forEach((h) => {
    state.nameById[h.id] = h.name;
  });
  renderChips();
  populateSelect();
  renderLists();

  document.getElementById("addBtn").addEventListener("click", onAddPick);
  document.getElementById("resetBtn").addEventListener("click", onReset);
  document.getElementById("heroSelect").addEventListener("change", updateAddBtnState);
  document.getElementById("tabs").addEventListener("click", onTabClick);
  document.querySelectorAll(".seg-btn").forEach((btn) => btn.addEventListener("click", onSegClick));
}

init();
