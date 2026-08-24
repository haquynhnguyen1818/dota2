// Post-draft coach panel: unlocks once both teams have 5 picks and draws the
// power curve. Phase C of docs/coaching_plan.md.
//
// The curve is a HEURISTIC, not a win probability -- it averages each team's
// five heroes' individual win rates at a given game length and ignores hero
// interaction entirely. Never label it "win chance".

const COACH_ROLES = ["Carry", "Midlane", "Offlane", "Supports"];

// Deltas are small (often under 2 percentage points) because averaging five
// heroes pulls hard toward 50%. Auto-scaling from 0-100% would render every
// draft as two flat lines, so the y-axis fits the data -- but never tighter
// than this, or noise looks like signal.
const MIN_SPAN = 0.02;

const coachState = {
  myHeroName: null,
  role: "Carry",
  analysis: null,
  error: null,
  loading: false,
};

let coachSeq = 0;

function coachIsReady() {
  return state.opponentPicks.length === MAX_PICKS && state.allyPicks.length === MAX_PICKS;
}

function syncCoachHeroValue() {
  const el = document.getElementById("coachHeroValue");
  el.textContent = coachState.myHeroName || "Select your hero…";
  el.classList.toggle("placeholder", !coachState.myHeroName);
}

function syncCoachRoleValue() {
  const el = document.getElementById("coachRoleValue");
  el.textContent = coachState.role || "Select role…";
  el.classList.toggle("placeholder", !coachState.role);
}

async function refreshCoach() {
  const seq = ++coachSeq;

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
  syncCoachRoleValue();

  if (!coachIsReady()) {
    coachState.analysis = null;
    coachState.error = null;
    coachState.loading = false;
    renderCoach();
    return;
  }

  const myHeroId = state.idByName[coachState.myHeroName];
  coachState.loading = true;
  coachState.error = null;
  renderCoach();

  try {
    const result = await getDraftAnalysis(myHeroId, coachState.role, state.allyPicks, state.opponentPicks);
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

function setupCoach() {
  syncCoachHeroValue();
  syncCoachRoleValue();

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

  setupCombo({
    comboId: "coachRoleCombo",
    triggerId: "coachRoleTrigger",
    panelId: "coachRolePanel",
    listId: "coachRoleList",
    clearId: "coachRoleClear",
    valueId: "coachRoleValue",
    options: () => COACH_ROLES,
    getValue: () => coachState.role,
    onSelect: (v) => {
      coachState.role = v;
      syncCoachRoleValue();
      refreshCoach();
    },
    onClear: () => {
      coachState.role = "Carry";
      syncCoachRoleValue();
      refreshCoach();
    },
  });
}
