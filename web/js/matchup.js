const PAGE_SIZE = 10;
const MATCHUP_SCALE_MAX = 7;

const state = { heroes: [], role: "Carry", hero: "Anti-Mage", showAll: false, rows: null, error: null };

function syncValues() {
  const rv = document.getElementById("roleValue");
  rv.textContent = state.role || "Select role…";
  rv.classList.toggle("placeholder", !state.role);
  const hv = document.getElementById("heroValue");
  hv.textContent = state.hero || "Select hero…";
  hv.classList.toggle("placeholder", !state.hero);
}

function rowHTML(item, idx, total) {
  const sign = item.advantage >= 0 ? "pos" : "neg";
  let tier = "";
  if (idx < 3 && item.advantage > 0) tier = "tier-signal";
  if (idx >= total - 3 && item.advantage < 0) tier = "tier-signal";
  const barPct = Math.min(Math.abs(item.advantage * 100) / MATCHUP_SCALE_MAX, 1) * 50;
  const rank = String(item.rank_vs_hero).padStart(2, "0");
  const valueText = (item.advantage >= 0 ? "+" : "") + (item.advantage * 100).toFixed(2) + "%";
  const wrPct = item.hero_wr * 100;
  const wrClass = wrPct >= 50 ? "wr-good" : "";
  return `
    <div class="row ${tier} ${sign}" style="animation-delay:${Math.min(idx, 10) * 30}ms">
      <div class="row-rank">${rank}</div>
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
}

function render() {
  const strip = document.getElementById("contextStrip");
  const listBody = document.getElementById("listBody");
  const showMoreWrap = document.getElementById("showMoreWrap");
  const showMoreBtn = document.getElementById("showMoreBtn");
  const listCount = document.getElementById("listCount");
  const listTitle = document.getElementById("listTitle");

  if (!state.role || !state.hero) {
    strip.innerHTML = "";
    listTitle.textContent = "Ranked counters";
    listCount.textContent = "";
    showMoreWrap.style.display = "none";
    listBody.innerHTML = `
      <div class="empty-state">
        <div class="icon">?</div>
        <p>Choose a role and opponent hero</p>
        <div class="sub">Ranked counters will show up here once both are set.</div>
      </div>`;
    return;
  }

  if (state.error) {
    strip.innerHTML = `<span>Role <b>${state.role}</b></span><span class="sep">·</span><span>Opponent <b>${state.hero}</b></span>`;
    listTitle.textContent = "Ranked counters";
    listCount.textContent = "";
    showMoreWrap.style.display = "none";
    listBody.innerHTML = `
      <div class="empty-state">
        <div class="icon">—</div>
        <p>No matchup data yet</p>
        <div class="sub">This role/opponent combination hasn't been analyzed.</div>
      </div>`;
    return;
  }

  if (!state.rows) {
    listBody.innerHTML = `<div class="empty-state"><div class="icon">…</div><p>Loading…</p></div>`;
    return;
  }

  const baseline = state.rows[0].vs_hero_wr * 100;
  strip.innerHTML = `
    <span>Role <b>${state.role}</b></span>
    <span class="sep">·</span>
    <span>Opponent <b>${state.hero}</b></span>
    <span class="sep">·</span>
    <span>Opponent WR <b>${baseline.toFixed(2)}%</b></span>
  `;

  listTitle.textContent = "Ranked counters";
  listCount.textContent = state.rows.length + " heroes";

  const total = state.rows.length;
  const visible = state.showAll ? state.rows : state.rows.slice(0, PAGE_SIZE);
  listBody.innerHTML = visible.map((item, idx) => rowHTML(item, idx, total)).join("");

  if (total > PAGE_SIZE) {
    showMoreWrap.style.display = "block";
    showMoreBtn.textContent = state.showAll ? "Show top 10 only" : `Show all ${total} heroes`;
  } else {
    showMoreWrap.style.display = "none";
  }
}

async function loadRanking() {
  state.rows = null;
  state.error = null;
  render();
  if (!state.role || !state.hero) return;
  const heroId = state.heroes.find((h) => h.name === state.hero)?.id;
  if (!heroId) return;
  try {
    state.rows = await getMatchupAdvantage(state.role, heroId);
  } catch (e) {
    state.error = e;
  }
  render();
}

async function init() {
  state.heroes = await getHeroes();
  const heroNames = state.heroes.map((h) => h.name).sort((a, b) => a.localeCompare(b));

  setupCombo({
    comboId: "roleCombo",
    triggerId: "roleTrigger",
    panelId: "rolePanel",
    listId: "roleList",
    clearId: "roleClear",
    valueId: "roleValue",
    options: ROLES,
    getValue: () => state.role,
    onSelect: (v) => {
      state.role = v;
      state.showAll = false;
      syncValues();
      loadRanking();
    },
    onClear: () => {
      state.role = null;
      syncValues();
      loadRanking();
    },
  });

  setupCombo({
    comboId: "heroCombo",
    triggerId: "heroTrigger",
    panelId: "heroPanel",
    listId: "heroList",
    clearId: "heroClear",
    valueId: "heroValue",
    searchId: "heroSearch",
    options: heroNames,
    getValue: () => state.hero,
    onSelect: (v) => {
      state.hero = v;
      state.showAll = false;
      syncValues();
      loadRanking();
    },
    onClear: () => {
      state.hero = null;
      syncValues();
      loadRanking();
    },
  });

  document.getElementById("showMoreBtn").addEventListener("click", () => {
    state.showAll = !state.showAll;
    render();
  });

  syncValues();
  await loadRanking();
}

init();
