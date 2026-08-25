// Post-draft coach panel: unlocks once both teams have 5 picks and draws the
// power curve. Phase C of docs/coaching_plan.md.
//
// The curve is a HEURISTIC, not a win probability -- it averages each team's
// five heroes' individual win rates at a given game length and ignores hero
// interaction entirely. Never label it "win chance".

// Deltas are small (often under 2 percentage points) because averaging five
// heroes pulls hard toward 50%. Auto-scaling from 0-100% would render every
// draft as two flat lines, so the y-axis fits the data -- but never tighter
// than this, or noise looks like signal.
const MIN_SPAN = 0.02;

const coachState = {
  myHeroName: null,
  // Read by the power curve request too (harmlessly -- it ignores role), but
  // it only *matters* to /coach (Phase G), which is why the selector lives
  // here rather than being wired into the curve fetch below.
  myRole: null,
  analysis: null,
  error: null,
  loading: false,
  // The LLM guide (Phase H) is a separate, user-triggered request layered on
  // top of the curve above -- its own loading/result/error state, plus the
  // rate-limit and PIN-unlock flow.
  plan: null,
  planError: null,
  planLoading: false,
  detailOpen: false,
  rateLimited: null, // {calls_used, limit} from a 429, or null
  unlockError: null,
  unlockLoading: false,
};

let coachSeq = 0;
let planSeq = 0;

function resetCoachPlan() {
  planSeq++; // orphans any in-flight /coach or /coach/unlock request
  coachState.plan = null;
  coachState.planError = null;
  coachState.planLoading = false;
  coachState.detailOpen = false;
  coachState.rateLimited = null;
  coachState.unlockError = null;
  coachState.unlockLoading = false;
}

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value == null ? "" : String(value);
  return div.innerHTML;
}

function coachIsReady() {
  return state.opponentPicks.length === MAX_PICKS && state.allyPicks.length === MAX_PICKS;
}

function syncCoachHeroValue() {
  const el = document.getElementById("coachHeroValue");
  el.textContent = coachState.myHeroName || "Select your hero…";
  el.classList.toggle("placeholder", !coachState.myHeroName);
}

async function refreshCoach() {
  const seq = ++coachSeq;
  // Any pick change makes the previous LLM guide (if any) stale -- it was
  // generated for a different draft.
  resetCoachPlan();

  // Drop a "me" selection that is no longer on the team, and default to the
  // first ally so the curve is already on screen rather than behind a click.
  const allyNames = state.allyPicks.map((id) => state.nameById[id]);
  if (coachState.myHeroName && !allyNames.includes(coachState.myHeroName)) {
    coachState.myHeroName = null;
  }
  if (!coachState.myHeroName && allyNames.length > 0) {
    coachState.myHeroName = allyNames[0];
  }
  syncCoachHeroValue();

  if (!coachIsReady()) {
    coachState.analysis = null;
    coachState.error = null;
    coachState.loading = false;
    renderCoach();
    renderCoachPlan();
    return;
  }

  const myHeroId = state.idByName[coachState.myHeroName];
  coachState.loading = true;
  coachState.error = null;
  renderCoach();
  renderCoachPlan();

  try {
    const result = await getDraftAnalysis(myHeroId, null, state.allyPicks, state.opponentPicks);
    if (seq !== coachSeq) return; // a newer request has since superseded this one
    coachState.analysis = result;
  } catch (err) {
    if (seq !== coachSeq) return;
    coachState.analysis = null;
    coachState.error = "Could not load the power curve.";
  } finally {
    if (seq === coachSeq) {
      coachState.loading = false;
      renderCoach();
    }
  }
}

function buildCurveSVG(curve, crossoverBucket) {
  const W = 720;
  const H = 250;
  const padL = 50;
  const padR = 16;
  const padT = 18;
  const padB = 34;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;

  // Fit the axis to the data, but always keep 50% in frame -- it is the
  // reference every win rate is read against.
  const values = curve.flatMap((p) => [p.my_win_rate, p.their_win_rate]).concat([0.5]);
  let lo = Math.min(...values);
  let hi = Math.max(...values);
  const mid = (lo + hi) / 2;
  const span = Math.max(hi - lo, MIN_SPAN) * 1.3;
  lo = mid - span / 2;
  hi = mid + span / 2;

  const x = (i) => padL + (curve.length === 1 ? plotW / 2 : (i / (curve.length - 1)) * plotW);
  const y = (v) => padT + (1 - (v - lo) / (hi - lo)) * plotH;
  const pts = (key) => curve.map((p, i) => `${x(i).toFixed(1)},${y(p[key]).toFixed(1)}`).join(" ");

  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => lo + f * (hi - lo));
  const gridHTML = yTicks
    .map(
      (v) =>
        `<line x1="${padL}" y1="${y(v).toFixed(1)}" x2="${W - padR}" y2="${y(v).toFixed(1)}" class="cv-grid"/>` +
        `<text x="${padL - 8}" y="${(y(v) + 4).toFixed(1)}" class="cv-ytick">${(v * 100).toFixed(1)}%</text>`
    )
    .join("");

  const fiftyHTML =
    lo < 0.5 && hi > 0.5
      ? `<line x1="${padL}" y1="${y(0.5).toFixed(1)}" x2="${W - padR}" y2="${y(0.5).toFixed(
          1
        )}" class="cv-fifty"/>`
      : "";

  const xLabelsHTML = curve
    .map((p, i) =>
      i % 2 === 0
        ? `<text x="${x(i).toFixed(1)}" y="${H - 12}" class="cv-xtick">${p.minutes.split("-")[0]}</text>`
        : ""
    )
    .join("");

  const crossIdx = curve.findIndex((p) => p.bucket === crossoverBucket);
  const crossHTML =
    crossIdx >= 0
      ? `<line x1="${x(crossIdx).toFixed(1)}" y1="${padT}" x2="${x(crossIdx).toFixed(1)}" y2="${
          padT + plotH
        }" class="cv-cross"/>` +
        `<text x="${x(crossIdx).toFixed(1)}" y="${padT - 5}" class="cv-crosslabel">crossover</text>`
      : "";

  const dots = (key, cls) =>
    curve
      .map((p, i) => `<circle cx="${x(i).toFixed(1)}" cy="${y(p[key]).toFixed(1)}" r="2.6" class="${cls}"/>`)
      .join("");

  return `
    <svg class="curve-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" role="img"
         aria-label="Power curve: your team versus the enemy team, by game length">
      ${gridHTML}
      ${fiftyHTML}
      ${crossHTML}
      <polyline points="${pts("their_win_rate")}" class="cv-line cv-them"/>
      <polyline points="${pts("my_win_rate")}" class="cv-line cv-me"/>
      ${dots("their_win_rate", "cv-dot cv-them-dot")}
      ${dots("my_win_rate", "cv-dot cv-me-dot")}
      ${xLabelsHTML}
      <text x="${padL - 8}" y="${H - 12}" class="cv-axis-label">min</text>
    </svg>
  `;
}

function coachVerdictText(analysis) {
  const verdicts = {
    you_are_faster: "You are faster — force the pace and close early.",
    you_win_long: "You win long — survive the early game and scale.",
    even: "Even tempo — no clear timing edge either way.",
    unknown: "Not enough data to call a tempo.",
  };
  return verdicts[analysis.tempo_verdict] || analysis.tempo_verdict;
}

function renderCoach() {
  const body = document.getElementById("coachBody");
  const controls = document.getElementById("coachControls");

  if (!coachIsReady()) {
    const need = [];
    const allies = MAX_PICKS - state.allyPicks.length;
    const enemies = MAX_PICKS - state.opponentPicks.length;
    if (allies > 0) need.push(`${allies} more on your team`);
    if (enemies > 0) need.push(`${enemies} more opponent`);
    controls.style.display = "none";
    body.innerHTML = `<p class="chip-empty">Unlocks at a full draft — ${need.join(", ")}.</p>`;
    return;
  }

  controls.style.display = "flex";

  if (coachState.error) {
    body.innerHTML = `<p class="chip-empty">${coachState.error}</p>`;
    return;
  }
  if (coachState.loading && !coachState.analysis) {
    body.innerHTML = '<p class="chip-empty">Reading the draft…</p>';
    return;
  }
  if (!coachState.analysis) return;

  const a = coachState.analysis;
  if (a.power_curve.length === 0) {
    body.innerHTML = '<p class="chip-empty">No duration data for this draft.</p>';
    return;
  }

  const crossText = a.crossover_minutes
    ? `Crossover at <strong>${a.crossover_minutes} min</strong>`
    : "No crossover — one side leads throughout";

  body.innerHTML = `
    <p class="coach-verdict">${coachVerdictText(a)}</p>
    <p class="coach-cross">${crossText}</p>
    <div class="curve-legend">
      <span class="curve-key"><i class="cv-swatch me"></i>Your team</span>
      <span class="curve-key"><i class="cv-swatch them"></i>Enemy team</span>
      <span class="curve-key"><i class="cv-swatch fifty"></i>50%</span>
    </div>
    ${buildCurveSVG(a.power_curve, a.crossover_bucket)}
    <p class="coach-note">
      Power curve — the average win rate of each side's five heroes at a given game length.
      A heuristic for tempo, not a win probability: hero interaction isn't in it.
    </p>
  `;
}

// --------------------------------------------------------------------------
// LLM guide (Phase H)
// --------------------------------------------------------------------------

async function requestCoachPlan() {
  if (!coachIsReady() || !coachState.myHeroName) return;
  const seq = ++planSeq;
  const myHeroId = state.idByName[coachState.myHeroName];

  coachState.planLoading = true;
  coachState.planError = null;
  coachState.rateLimited = null;
  renderCoachPlan();

  try {
    const result = await getCoachPlan(myHeroId, coachState.myRole, state.allyPicks, state.opponentPicks);
    if (seq !== planSeq) return; // superseded by a pick/role change since this fired

    if (result.ok) {
      coachState.plan = result.data;
    } else if (result.status === 429 && result.data && result.data.detail) {
      coachState.rateLimited = result.data.detail;
    } else {
      coachState.planError = "Could not generate the coaching guide.";
    }
  } catch (err) {
    if (seq !== planSeq) return;
    coachState.planError = "Could not reach the server.";
  } finally {
    if (seq === planSeq) {
      coachState.planLoading = false;
      renderCoachPlan();
    }
  }
}

async function requestUnlock() {
  const input = document.getElementById("coachPinInput");
  const pin = input ? input.value.trim() : "";
  if (!pin) return;

  coachState.unlockLoading = true;
  coachState.unlockError = null;
  renderCoachPlan();

  try {
    const result = await unlockCoach(pin);
    if (result.ok) {
      coachState.rateLimited = null;
      coachState.unlockLoading = false;
      await requestCoachPlan(); // retry now that the budget is raised; it renders on completion
    } else {
      coachState.unlockLoading = false;
      coachState.unlockError = typeof result.data?.detail === "string" ? result.data.detail : "Incorrect PIN.";
      renderCoachPlan();
    }
  } catch (err) {
    coachState.unlockLoading = false;
    coachState.unlockError = "Could not reach the server.";
    renderCoachPlan();
  }
}

function renderCoachPlan() {
  const el = document.getElementById("coachPlanBody");
  if (!coachIsReady()) {
    el.innerHTML = "";
    return;
  }

  if (coachState.rateLimited) {
    const rl = coachState.rateLimited;
    el.innerHTML = `
      <div class="plan-limit">
        <p class="plan-limit-msg">
          You've used ${rl.calls_used}/${rl.limit} coaching guides in the last 45 minutes.
          Enter the PIN to unlock 5 more.
        </p>
        <div class="plan-unlock-row">
          <input type="password" inputmode="numeric" class="plan-pin-input" id="coachPinInput" placeholder="PIN"
                 ${coachState.unlockLoading ? "disabled" : ""}>
          <button class="btn btn-primary" id="coachUnlockBtn" ${coachState.unlockLoading ? "disabled" : ""}>
            ${coachState.unlockLoading ? "Checking…" : "Unlock +5"}
          </button>
        </div>
        ${coachState.unlockError ? `<p class="plan-unlock-error">${escapeHtml(coachState.unlockError)}</p>` : ""}
      </div>
    `;
    attachCoachPlanHandlers();
    return;
  }

  if (coachState.planLoading) {
    el.innerHTML = '<p class="chip-empty">Writing your game plan…</p>';
    return;
  }

  if (coachState.planError) {
    el.innerHTML = `
      <p class="chip-empty">${escapeHtml(coachState.planError)}</p>
      <button class="btn btn-ghost plan-btn" id="coachPlanBtn">Try again</button>
    `;
    attachCoachPlanHandlers();
    return;
  }

  if (!coachState.plan) {
    el.innerHTML = `<button class="btn btn-primary plan-btn" id="coachPlanBtn">Get coaching guide</button>`;
    attachCoachPlanHandlers();
    return;
  }

  const p = coachState.plan;
  const open = coachState.detailOpen;
  el.innerHTML = `
    <div class="coach-plan">
      <p class="plan-frame">${escapeHtml(p.frame)}</p>
      <div class="plan-grid">
        <div class="plan-block">
          <p class="plan-label">Lane</p>
          <p class="plan-text">${escapeHtml(p.lane.instruction)}</p>
          <p class="plan-text plan-sub">First item — ${escapeHtml(p.lane.first_item)}</p>
          <p class="plan-text plan-risk">${escapeHtml(p.lane.risk)}</p>
        </div>
        <div class="plan-block">
          <p class="plan-label">Clock</p>
          <p class="plan-text">${escapeHtml(p.clock.your_window)}</p>
          <p class="plan-text plan-sub">Their spike — ${escapeHtml(p.clock.their_spike)}</p>
        </div>
      </div>
      <p class="plan-wincon"><span class="plan-label">Wincon</span> ${escapeHtml(p.wincon)}</p>
      <button class="plan-detail-toggle" id="planDetailToggle" aria-expanded="${open}">
        <span>Full game plan</span>
        <span class="plan-detail-chevron"></span>
      </button>
      ${
        open
          ? `
        <div class="plan-detail">
          <div class="plan-detail-row"><span class="plan-detail-stage">Early</span>${escapeHtml(p.detail.early)}</div>
          <div class="plan-detail-row"><span class="plan-detail-stage">Mid</span>${escapeHtml(p.detail.mid)}</div>
          <div class="plan-detail-row"><span class="plan-detail-stage">Late</span>${escapeHtml(p.detail.late)}</div>
        </div>
      `
          : ""
      }
    </div>
  `;
  attachCoachPlanHandlers();
}

function attachCoachPlanHandlers() {
  const btn = document.getElementById("coachPlanBtn");
  if (btn) btn.addEventListener("click", requestCoachPlan);

  const toggle = document.getElementById("planDetailToggle");
  if (toggle) {
    toggle.addEventListener("click", () => {
      coachState.detailOpen = !coachState.detailOpen;
      renderCoachPlan();
    });
  }

  const unlockBtn = document.getElementById("coachUnlockBtn");
  if (unlockBtn) unlockBtn.addEventListener("click", requestUnlock);

  const pinInput = document.getElementById("coachPinInput");
  if (pinInput) {
    pinInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        requestUnlock();
      }
    });
  }
}

function syncCoachRoleUI() {
  document.querySelectorAll("#coachRoleTabs .role-pill").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.role === coachState.myRole);
  });
}

function setupCoachRoleTabs() {
  document.getElementById("coachRoleTabs").addEventListener("click", (e) => {
    const btn = e.target.closest(".role-pill");
    if (!btn) return;
    const role = btn.dataset.role;
    coachState.myRole = coachState.myRole === role ? null : role;
    syncCoachRoleUI();
    resetCoachPlan();
    renderCoachPlan();
  });
}

function setupCoach() {
  syncCoachHeroValue();
  syncCoachRoleUI();
  setupCoachRoleTabs();

  setupCombo({
    comboId: "coachHeroCombo",
    triggerId: "coachHeroTrigger",
    panelId: "coachHeroPanel",
    listId: "coachHeroList",
    clearId: "coachHeroClear",
    valueId: "coachHeroValue",
    options: () => state.allyPicks.map((id) => state.nameById[id]),
    getValue: () => coachState.myHeroName,
    onSelect: (v) => {
      coachState.myHeroName = v;
      syncCoachHeroValue();
      refreshCoach();
    },
    onClear: () => {
      coachState.myHeroName = null;
      syncCoachHeroValue();
      refreshCoach();
    },
  });
}
