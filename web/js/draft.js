const BEST_PAGE_SIZE = 10;

const state = {
  heroes: [],
  nameById: {},
  idByName: {},
  opponentPicks: [],
  pendingPickName: null,
  allyPicks: [],
  pendingAllyPickName: null,
  players: [],
  accountIdByName: {},
  playerName: null,
  currentRole: "Carry",
  suggestionsByRole: null,
  suggestionsForPicks: null, // {opponentPicks, allyPicks, playerAccountId} state.suggestionsByRole was fetched for
  expanded: {},
  showAllBest: {}, // per-role: show all 20 best vs. just the top 10
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

function syncHeroPickValue() {
  const el = document.getElementById("heroPickValue");
  el.textContent = state.pendingPickName || "Select hero…";
  el.classList.toggle("placeholder", !state.pendingPickName);
  updateAddBtnState();
}

function updateAddBtnState() {
  document.getElementById("addBtn").disabled = !state.pendingPickName || state.opponentPicks.length >= MAX_PICKS;
}

async function onAddPick() {
  if (!state.pendingPickName) return;
  const id = state.idByName[state.pendingPickName];
  if (!id) return;
  state.opponentPicks.push(id);
  state.pendingPickName = null;
  syncHeroPickValue();
  renderChips();
  await refreshSuggestions();
}

async function removePick(id) {
  state.opponentPicks = state.opponentPicks.filter((h) => h !== id);
  renderChips();
  syncHeroPickValue();
  await refreshSuggestions();
}

async function onReset() {
  state.opponentPicks = [];
  state.pendingPickName = null;
  syncHeroPickValue();
  renderChips();
  await refreshSuggestions();
}

function renderAllyChips() {
  const el = document.getElementById("allyChips");
  if (state.allyPicks.length === 0) {
    el.innerHTML = '<span class="chip-empty">No ally picks yet</span>';
    return;
  }
  el.innerHTML = state.allyPicks
    .map(
      (id) => `
    <span class="chip">${state.nameById[id]}
      <button aria-label="Remove ${state.nameById[id]}" data-remove-ally="${id}">×</button>
    </span>
  `
    )
    .join("");
  el.querySelectorAll("button[data-remove-ally]").forEach((btn) => {
    btn.addEventListener("click", () => removeAllyPick(Number(btn.dataset.removeAlly)));
  });
}

function syncAllyPickValue() {
  const el = document.getElementById("allyPickValue");
  el.textContent = state.pendingAllyPickName || "Select hero…";
  el.classList.toggle("placeholder", !state.pendingAllyPickName);
  updateAllyAddBtnState();
}

function updateAllyAddBtnState() {
  document.getElementById("allyAddBtn").disabled =
    !state.pendingAllyPickName || state.allyPicks.length >= MAX_PICKS;
}

async function onAddAllyPick() {
  if (!state.pendingAllyPickName) return;
  const id = state.idByName[state.pendingAllyPickName];
  if (!id) return;
  state.allyPicks.push(id);
  state.pendingAllyPickName = null;
  syncAllyPickValue();
  renderAllyChips();
  await refreshSuggestions();
}

async function removeAllyPick(id) {
  state.allyPicks = state.allyPicks.filter((h) => h !== id);
  renderAllyChips();
  syncAllyPickValue();
  await refreshSuggestions();
}

async function onAllyReset() {
  state.allyPicks = [];
  state.pendingAllyPickName = null;
  syncAllyPickValue();
  renderAllyChips();
  await refreshSuggestions();
}

async function onPlayerSelect(name) {
  state.playerName = name;
  syncPlayerValue();
  await refreshSuggestions();
}

async function onPlayerClear() {
  state.playerName = null;
  syncPlayerValue();
  await refreshSuggestions();
}

function syncPlayerValue() {
  const el = document.getElementById("playerValue");
  el.textContent = state.playerName || "None selected…";
  el.classList.toggle("placeholder", !state.playerName);
}

async function refreshSuggestions() {
  state.expanded = {};
  state.showAllBest = {};
  const seq = ++requestSeq;
  const picksSnapshot = [...state.opponentPicks];
  const alliesSnapshot = [...state.allyPicks];
  const playerAccountId = state.playerName ? state.accountIdByName[state.playerName] : null;
  if (picksSnapshot.length === 0) {
    state.suggestionsByRole = null;
    state.suggestionsForPicks = null;
    renderLists();
    return;
  }
  const result = await getDraftSuggestions(picksSnapshot, alliesSnapshot, playerAccountId);
  if (seq !== requestSeq) return; // a newer request has since superseded this one
  state.suggestionsByRole = {};
  result.roles.forEach((r) => {
    state.suggestionsByRole[r.role] = { best: r.best, worst: r.worst };
  });
  state.suggestionsForPicks = { picksSnapshot, alliesSnapshot, playerAccountId };
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
    const history = item.player_history;
    const historyText = history
      ? `  ·  You: ${history.games_played}g, ${(history.win_rate * 100).toFixed(1)}% WR`
      : "";
    html += `
      <div class="row ${tier} ${sign} clickable" data-hero-id="${item.hero_id}" data-role="${role}" data-kind="${kind}" style="animation-delay:${Math.min(idx, 10) * 30}ms">
        <div class="row-rank">${String(idx + 1).padStart(2, "0")}</div>
        <div class="row-main">
          <div class="row-name" title="${item.hero_name}">${item.hero_name}</div>
          <div class="row-wr ${wrClass}">WR ${wrPct.toFixed(2)}%${historyText}</div>
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
      item.synergy_breakdown.forEach((s) => {
        const sSign = s.synergy >= 0 ? "pos" : "neg";
        const sValueText = (s.synergy >= 0 ? "+" : "") + (s.synergy * 100).toFixed(2) + "%";
        html += `
          <div class="row sub-row ${sSign}">
            <div class="row-rank"></div>
            <div class="row-main">
              <div class="row-name">↳ with ${s.with_hero_name}</div>
            </div>
            <div class="row-bar-track"></div>
            <div class="row-value ${sSign}">${sValueText}</div>
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
  const bestShowMoreWrap = document.getElementById("bestShowMoreWrap");
  const bestShowMoreBtn = document.getElementById("bestShowMoreBtn");

  if (!state.suggestionsByRole) {
    bestEl.innerHTML = '<p class="chip-empty">Add an opponent pick to see suggestions.</p>';
    worstEl.innerHTML = "";
    document.getElementById("bestCount").textContent = "";
    document.getElementById("worstCount").textContent = "";
    bestShowMoreWrap.style.display = "none";
    return;
  }

  const data = state.suggestionsByRole[state.currentRole];
  const showAllBest = state.showAllBest[state.currentRole] ?? false;
  const bestVisible = showAllBest ? data.best : data.best.slice(0, BEST_PAGE_SIZE);

  bestEl.innerHTML = buildRowsHTML(bestVisible, state.currentRole, "best");
  worstEl.innerHTML = buildRowsHTML(data.worst, state.currentRole, "worst");
  document.getElementById("bestCount").textContent = data.best.length + " heroes";
  document.getElementById("worstCount").textContent = data.worst.length + " heroes";

  if (data.best.length > BEST_PAGE_SIZE) {
    bestShowMoreWrap.style.display = "block";
    bestShowMoreBtn.textContent = showAllBest ? "Show top 10 only" : `Show all ${data.best.length} heroes`;
  } else {
    bestShowMoreWrap.style.display = "none";
  }

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
  const [heroes, players] = await Promise.all([getHeroes(), getPlayers()]);
  state.heroes = heroes;
  state.heroes.forEach((h) => {
    state.nameById[h.id] = h.name;
    state.idByName[h.name] = h.id;
  });
  state.players = players;
  state.players.forEach((p) => {
    state.accountIdByName[p.name] = p.account_id;
  });
  renderChips();
  syncHeroPickValue();
  renderAllyChips();
  syncAllyPickValue();
  syncPlayerValue();
  renderLists();

  setupCombo({
    comboId: "heroPickCombo",
    triggerId: "heroPickTrigger",
    panelId: "heroPickPanel",
    listId: "heroPickList",
    clearId: "heroPickClear",
    valueId: "heroPickValue",
    searchId: "heroPickSearch",
    options: () =>
      state.heroes
        .filter((h) => !state.opponentPicks.includes(h.id) && !state.allyPicks.includes(h.id))
        .map((h) => h.name)
        .sort((a, b) => a.localeCompare(b)),
    getValue: () => state.pendingPickName,
    onSelect: (v) => {
      state.pendingPickName = v;
      syncHeroPickValue();
    },
    onClear: () => {
      state.pendingPickName = null;
      syncHeroPickValue();
    },
  });

  setupCombo({
    comboId: "allyPickCombo",
    triggerId: "allyPickTrigger",
    panelId: "allyPickPanel",
    listId: "allyPickList",
    clearId: "allyPickClear",
    valueId: "allyPickValue",
    searchId: "allyPickSearch",
    options: () =>
      state.heroes
        .filter((h) => !state.allyPicks.includes(h.id) && !state.opponentPicks.includes(h.id))
        .map((h) => h.name)
        .sort((a, b) => a.localeCompare(b)),
    getValue: () => state.pendingAllyPickName,
    onSelect: (v) => {
      state.pendingAllyPickName = v;
      syncAllyPickValue();
    },
    onClear: () => {
      state.pendingAllyPickName = null;
      syncAllyPickValue();
    },
  });

  setupCombo({
    comboId: "playerCombo",
    triggerId: "playerTrigger",
    panelId: "playerPanel",
    listId: "playerList",
    clearId: "playerClear",
    valueId: "playerValue",
    options: () => state.players.map((p) => p.name).sort((a, b) => a.localeCompare(b)),
    getValue: () => state.playerName,
    onSelect: onPlayerSelect,
    onClear: onPlayerClear,
  });

  document.getElementById("addBtn").addEventListener("click", onAddPick);
  document.getElementById("resetBtn").addEventListener("click", onReset);
  document.getElementById("allyAddBtn").addEventListener("click", onAddAllyPick);
  document.getElementById("allyResetBtn").addEventListener("click", onAllyReset);
  document.getElementById("tabs").addEventListener("click", onTabClick);
  document.querySelectorAll(".seg-btn").forEach((btn) => btn.addEventListener("click", onSegClick));
  document.getElementById("bestShowMoreBtn").addEventListener("click", () => {
    state.showAllBest[state.currentRole] = !(state.showAllBest[state.currentRole] ?? false);
    renderLists();
  });
}

init();
