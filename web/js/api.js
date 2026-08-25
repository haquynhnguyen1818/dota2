async function apiGet(path) {
  const res = await fetch(`${API_BASE_URL}${path}`);
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`);
  return res.json();
}

async function apiPost(path, body) {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`POST ${path} failed: ${res.status}`);
  return res.json();
}

function getHeroes() {
  return apiGet("/heroes");
}

function getPlayers() {
  return apiGet("/players");
}

function getMatchupAdvantage(role, vsHeroId) {
  return apiGet(`/matchup-advantage/${encodeURIComponent(role)}/${vsHeroId}`);
}

function getDraftSuggestions(opponentPicks, allyPicks, playerAccountId) {
  return apiPost("/draft-suggestions", {
    opponent_picks: opponentPicks,
    ally_picks: allyPicks,
    player_account_id: playerAccountId,
  });
}

function getDraftAnalysis(myHeroId, myRole, allyPicks, enemyPicks) {
  return apiPost("/draft-analysis", {
    my_hero_id: myHeroId,
    my_role: myRole,
    ally_picks: allyPicks,
    enemy_picks: enemyPicks,
  });
}

// Unlike apiPost, this doesn't throw on a non-2xx response -- the coach panel
// needs the parsed body (rate-limit detail, wrong-PIN message) either way.
async function apiPostResult(path, body) {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  let data = null;
  try {
    data = await res.json();
  } catch (_) {
    // no JSON body
  }
  return { ok: res.ok, status: res.status, data };
}

function getCoachPlan(myHeroId, myRole, allyPicks, enemyPicks, language) {
  return apiPostResult("/coach", {
    my_hero_id: myHeroId,
    my_role: myRole,
    ally_picks: allyPicks,
    enemy_picks: enemyPicks,
    language: language,
  });
}

function unlockCoach(pin) {
  return apiPostResult("/coach/unlock", { pin });
}
