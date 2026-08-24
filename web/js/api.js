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
