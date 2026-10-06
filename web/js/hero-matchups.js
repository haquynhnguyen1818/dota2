// Second section on matchup.html: pick one hero, see its own win rate plus its
// best and worst matchups against every other hero.
//
// Deliberately a separate file from matchup.js. Both are plain scripts sharing
// one global scope, so every top-level name here is prefixed (`hmState`,
// `HM_*`) -- `state`, `PAGE_SIZE` and `MATCHUP_SCALE_MAX` are already taken by
// matchup.js and redeclaring a `const` would break the page.

const HM_PAGE_SIZE = 10;
const HM_SCALE_MAX = 7; // same bar scale as the ranked-counters list above

const hmState = { hero: null, data: null, error: null, showAll: false, view: "best" };

function hmSyncValue() {
  const el = document.getElementById("hmHeroValue");
  el.textContent = hmState.hero || "Select hero…";
  el.classList.toggle("placeholder", !hmState.hero);
}

// `idx` is only for the stagger; tier highlighting keys off the sign, since a
// "best" row that is still negative shouldn't read as a good matchup.
function hmRowHTML(item, idx, isBest) {
  const sign = item.advantage >= 0 ? "pos" : "neg";
  const tier = (isBest && item.advantage > 0) || (!isBest && item.advantage < 0) ? "tier-signal" : "";
  const barPct = Math.min(Math.abs(item.advantage * 100) / HM_SCALE_MAX, 1) * 50;
  const valueText = (item.advantage >= 0 ? "+" : "") + (item.advantage * 100).toFixed(2) + "%";
  const wrPct = item.wr_a_b * 100;
  const wrClass = wrPct >= 50 ? "wr-good" : "";
  return `
    <div class="row ${tier} ${sign}" style="animation-delay:${Math.min(idx, 10) * 30}ms">
      <div class="row-rank">${String(idx + 1).padStart(2, "0")}</div>
      <div class="row-main">
        <div class="row-name" title="${item.vs_hero_name}">${item.vs_hero_name}</div>
        <div class="row-wr ${wrClass}">WR ${wrPct.toFixed(2)}% vs them</div>
      </div>
      <div class="row-bar-track">
        <div class="row-bar ${sign}" style="width:${barPct}%;"></div>
      </div>
      <div class="row-value ${sign}">${valueText}</div>
    </div>
  `;
}

function hmRender() {
  const strip = document.getElementById("hmContextStrip");
  const bestEl = document.getElementById("hmBestList");
  const worstEl = document.getElementById("hmWorstList");
  const bestCount = document.getElementById("hmBestCount");
  const worstCount = document.getElementById("hmWorstCount");
  const moreWrap = document.getElementById("hmShowMoreWrap");
  const moreBtn = document.getElementById("hmShowMoreBtn");

  const placeholder = (icon, text, sub) => {
    strip.innerHTML = hmState.hero ? `<span>Hero <b>${hmState.hero}</b></span>` : "";
    bestEl.innerHTML = `<div class="empty-state"><div class="icon">${icon}</div><p>${text}</p>${
      sub ? `<div class="sub">${sub}</div>` : ""
    }</div>`;
    worstEl.innerHTML = "";
    bestCount.textContent = "";
    worstCount.textContent = "";
    moreWrap.style.display = "none";
  };

  if (!hmState.hero) {
    return placeholder("?", "Choose a hero", "Its win rate and matchups will show up here.");
  }
  if (hmState.error) {
    return placeholder("—", "No matchup data for this hero", "This hero isn't in any role list yet.");
  }
  if (!hmState.data) {
    return placeholder("…", "Loading…");
  }

  const { hero_name, hero_wr, matchups } = hmState.data;
  const wrPct = hero_wr * 100;
  strip.innerHTML = `
    <span>Hero <b>${hero_name}</b></span>
    <span class="sep">·</span>
    <span>Overall WR <b class="${wrPct >= 50 ? "wr-good" : ""}">${wrPct.toFixed(2)}%</b></span>
    <span class="sep">·</span>
    <span>Opponents <b>${matchups.length}</b></span>
  `;

  // matchups arrives sorted by advantage descending, so the head is the
  // advantages and the tail is the disadvantages, reversed so the worst is first.
  const bestAll = matchups.filter((m) => m.advantage > 0);
  const worstAll = matchups.filter((m) => m.advantage < 0).slice().reverse();
  const bestVisible = hmState.showAll ? bestAll : bestAll.slice(0, HM_PAGE_SIZE);

  bestEl.innerHTML =
    bestVisible.map((m, i) => hmRowHTML(m, i, true)).join("") ||
    `<p class="chip-empty">No favourable matchups.</p>`;
  worstEl.innerHTML =
    worstAll.slice(0, HM_PAGE_SIZE).map((m, i) => hmRowHTML(m, i, false)).join("") ||
    `<p class="chip-empty">No unfavourable matchups.</p>`;
  bestCount.textContent = bestAll.length + " heroes";
  worstCount.textContent = worstAll.length + " heroes";

  if (bestAll.length > HM_PAGE_SIZE) {
    moreWrap.style.display = "block";
    moreBtn.textContent = hmState.showAll
      ? "Show top 10 only"
      : `Show all ${bestAll.length} advantages`;
  } else {
    moreWrap.style.display = "none";
  }
}

// Mobile-only best/worst toggle -- the two-column grid collapses under 760px and
// the segmented control picks which column shows. Same mechanism as draft.js.
function hmSetView(view) {
  hmState.view = view;
  const grid = document.getElementById("hmListsGrid");
  grid.classList.remove("show-best", "show-worst");
  grid.classList.add(view === "best" ? "show-best" : "show-worst");
  document.querySelectorAll("#hmSegmented .seg-btn").forEach((btn) => {
    const on = btn.dataset.view === view;
    btn.classList.toggle("active", on);
    btn.classList.toggle("pos", on && view === "best");
    btn.classList.toggle("neg", on && view === "worst");
  });
}

async function hmLoad() {
  hmState.data = null;
  hmState.error = null;
  hmRender();
  if (!hmState.hero) return;
  const heroId = hmState.heroes.find((h) => h.name === hmState.hero)?.id;
  if (!heroId) return;
  // Stale-response guard, same reason as draft.js's: switching heroes quickly
  // fires overlapping requests and a slower earlier one must not overwrite a
  // faster later one.
  const seq = ++hmState.seq;
  try {
    const data = await getHeroMatchups(heroId);
    if (seq !== hmState.seq) return;
    hmState.data = data;
  } catch (e) {
    if (seq !== hmState.seq) return;
    hmState.error = e;
  }
  hmRender();
}

async function hmInit(heroes) {
  hmState.heroes = heroes;
  hmState.seq = 0;
  const names = heroes.map((h) => h.name).sort((a, b) => a.localeCompare(b));

  setupCombo({
    comboId: "hmHeroCombo",
    triggerId: "hmHeroTrigger",
    panelId: "hmHeroPanel",
    listId: "hmHeroList",
    clearId: "hmHeroClear",
    valueId: "hmHeroValue",
    searchId: "hmHeroSearch",
    options: names,
    getValue: () => hmState.hero,
    onSelect: (v) => {
      hmState.hero = v;
      hmState.showAll = false;
      hmSyncValue();
      hmLoad();
    },
    onClear: () => {
      hmState.hero = null;
      hmSyncValue();
      hmLoad();
    },
  });

  document.getElementById("hmShowMoreBtn").addEventListener("click", () => {
    hmState.showAll = !hmState.showAll;
    hmRender();
  });
  document.querySelectorAll("#hmSegmented .seg-btn").forEach((btn) => {
    btn.addEventListener("click", () => hmSetView(btn.dataset.view));
  });

  hmSetView("best");
  hmSyncValue();
  hmRender();
}
