const state = {
  leagueId: null,
  userId: null,
  teams: [],
  rosterPositions: [],
  myRosterId: null,
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

function dynastyQueryParam() {
  return $('#is-dynasty-override').checked ? 'force_dynasty=true' : '';
}

function withDynastyParam(url) {
  const extra = dynastyQueryParam();
  if (!extra) return url;
  return url + (url.includes('?') ? '&' : '?') + extra;
}

$('#is-dynasty-override').addEventListener('change', () => {
  loadDashboard();
  loadTradeSide('a');
  loadTradeSide('b');
  if (!$('#recommend').classList.contains('hidden')) {
    loadRecommendations();
    loadShopPlayers();
  }
});

async function api(path, options) {
  const resp = await fetch(path, options);
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(body.detail || `Request failed: ${resp.status}`);
  }
  return resp.json();
}

function showTab(name) {
  $$('.tab-pane').forEach((el) => el.classList.add('hidden'));
  $(`#${name}`).classList.remove('hidden');
  $$('#tabs button[data-tab]').forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.tab === name);
  });
}

// ---------- Setup ----------

$('#find-leagues-btn').addEventListener('click', async () => {
  const username = $('#username-input').value.trim();
  const season = $('#season-input').value.trim();
  $('#setup-error').textContent = '';
  if (!username) return;

  try {
    const data = await api(`/api/user/${encodeURIComponent(username)}/leagues?season=${encodeURIComponent(season)}`);
    state.userId = data.user_id;

    const list = $('#league-list');
    list.innerHTML = '';
    if (data.leagues.length === 0) {
      list.textContent = 'No leagues found for that username/season.';
      return;
    }
    data.leagues.forEach((lg) => {
      const btn = document.createElement('button');
      btn.textContent = `${lg.name} (${lg.season})`;
      btn.addEventListener('click', () => selectLeague(lg.league_id));
      list.appendChild(btn);
    });
  } catch (err) {
    $('#setup-error').textContent = err.message;
  }
});

async function selectLeague(leagueId) {
  const overview = await api(`/api/league/${leagueId}`);
  state.leagueId = leagueId;
  state.teams = overview.teams;
  state.rosterPositions = overview.roster_positions;

  const mine = overview.teams.find((t) => t.owner_id === state.userId);
  if (mine) {
    state.myRosterId = mine.roster_id;
  } else {
    const pick = prompt(
      `Could not auto-detect your team. Enter your team name from this list:\n` +
        overview.teams.map((t) => t.team_name).join('\n')
    );
    const match = overview.teams.find((t) => t.team_name === pick);
    state.myRosterId = match ? match.roster_id : overview.teams[0].roster_id;
  }

  $('#tabs').classList.remove('hidden');
  $('#setup').classList.add('hidden');
  populateTeamSelects();
  showTab('dashboard');
  loadDashboard();
}

$('#change-league-btn').addEventListener('click', () => {
  $('#setup').classList.remove('hidden');
  $('#tabs').classList.add('hidden');
  $$('.tab-pane').forEach((el) => el.classList.add('hidden'));
});

$$('#tabs button[data-tab]').forEach((btn) => {
  btn.addEventListener('click', () => {
    showTab(btn.dataset.tab);
    if (btn.dataset.tab === 'recommend') {
      loadRecommendations();
      loadShopPlayers();
    }
    if (btn.dataset.tab === 'league') {
      loadLeagueAnalysis();
    }
  });
});

// ---------- Dashboard ----------

async function loadDashboard() {
  const roster = await api(withDynastyParam(`/api/league/${state.leagueId}/roster/${state.myRosterId}/valued`));
  const container = $('#my-roster');
  container.innerHTML = `<h3>${roster.team_name} — Total Value: ${roster.total_value}</h3>`;
  container.appendChild(renderPlayerTable(roster.players));
}

function renderPlayerTable(players) {
  const table = document.createElement('table');
  table.innerHTML = `<thead><tr><th>Player</th><th>Pos</th><th>Team</th><th>Value</th><th>Pos Rank</th><th>30d Trend</th></tr></thead>`;
  const tbody = document.createElement('tbody');
  players.forEach((p) => {
    const tr = document.createElement('tr');
    if (p.unvalued) tr.classList.add('unvalued');
    tr.innerHTML = `<td>${p.name}</td><td>${p.position}</td><td>${p.team || '-'}</td>` +
      `<td>${p.value}</td><td>${p.position_rank ?? '-'}</td><td>${p.trend_30_day ?? '-'}</td>`;
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  return table;
}

// ---------- Trade Calculator ----------

const PACKAGE_POSITIONS = ['QB', 'RB', 'WR', 'TE'];

function populateTeamSelects() {
  ['#team-a-select', '#team-b-select'].forEach((sel) => {
    const el = $(sel);
    el.innerHTML = '';
    state.teams.forEach((t) => {
      const opt = document.createElement('option');
      opt.value = t.roster_id;
      opt.textContent = t.team_name + (t.roster_id === state.myRosterId ? ' (me)' : '');
      el.appendChild(opt);
    });
  });
  $('#team-a-select').value = state.myRosterId;
  loadTradeSide('a');
  loadTradeSide('b');
  loadPackagePositionFilter();
}

$('#team-a-select').addEventListener('change', () => {
  loadTradeSide('a');
  loadPackagePositionFilter();
});
$('#team-b-select').addEventListener('change', () => loadTradeSide('b'));

async function loadPackagePositionFilter() {
  const teamARosterId = $('#team-a-select').value;
  const data = await api(withDynastyParam(`/api/league/${state.leagueId}/roster/${teamARosterId}/recommendations`));
  const container = $('#package-positions');
  container.innerHTML = '';
  PACKAGE_POSITIONS.forEach((pos) => {
    const needed = data.needs_summary[pos] && data.needs_summary[pos].need_score > 0;
    const label = document.createElement('label');
    label.innerHTML = `<input type="checkbox" value="${pos}" ${needed ? 'checked' : ''}> ${pos}`;
    container.appendChild(label);
  });
}

function selectedPackagePositions() {
  const checked = Array.from($('#package-positions').querySelectorAll('input:checked')).map((el) => el.value);
  return checked.length > 0 ? checked : null;
}

async function loadTradeSide(side) {
  const rosterId = $(`#team-${side}-select`).value;
  const roster = await api(withDynastyParam(`/api/league/${state.leagueId}/roster/${rosterId}/valued`));
  const container = $(`#team-${side}-players`);
  container.innerHTML = '';
  roster.players.forEach((p) => {
    const label = document.createElement('label');
    label.className = 'player-checkbox';
    label.innerHTML = `<input type="checkbox" value="${p.player_id}"> ${p.name} (${p.position}, ${p.value})`;
    container.appendChild(label);
  });
}

function selectedPlayerIds(side) {
  return Array.from($(`#team-${side}-players`).querySelectorAll('input:checked')).map((el) => el.value);
}

$('#evaluate-trade-btn').addEventListener('click', async () => {
  const side_a = selectedPlayerIds('a');
  const side_b = selectedPlayerIds('b');
  const result = await api(withDynastyParam(`/api/league/${state.leagueId}/trade`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ side_a, side_b }),
  });
  renderTradeResult(result);
});

async function runPackageSearch(targetRosterId) {
  const player_ids = selectedPlayerIds('a');
  const container = $('#package-suggestions');
  if (player_ids.length === 0) {
    container.innerHTML = '<p class="warn">Check at least one Team A player to shop as a package.</p>';
    return;
  }

  const teamARosterId = $('#team-a-select').value;
  const positions = selectedPackagePositions();

  const data = await api(withDynastyParam(`/api/league/${state.leagueId}/roster/${teamARosterId}/suggest-package`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ player_ids, target_roster_id: targetRosterId, positions }),
  });
  renderPackageSuggestions(data);
}

$('#propose-package-btn').addEventListener('click', () => {
  const teamARosterId = $('#team-a-select').value;
  const teamBRosterId = $('#team-b-select').value;
  if (teamARosterId === teamBRosterId) {
    $('#package-suggestions').innerHTML = '<p class="warn">Pick a different Team B to propose this package to.</p>';
    return;
  }
  runPackageSearch(Number(teamBRosterId));
});

$('#find-package-all-btn').addEventListener('click', () => runPackageSearch(null));

function renderPackageSuggestions(data) {
  const container = $('#package-suggestions');
  container.innerHTML = `<p class="reason">Giving up ${data.give_total_raw} raw value
    (${data.give_total_effective} effective, after factoring Team A's positional surplus/need).</p>`;

  if (data.matches.length === 0) {
    container.innerHTML += '<p>No package matches found in range — try widening the package or checking different players.</p>';
    return;
  }

  data.matches.forEach((m) => {
    const card = document.createElement('div');
    card.className = 'suggestion-card';
    const names = m.get.map((p) => `${p.name} (${p.position}, ${p.value})`).join(' + ');
    const positions = m.get_positions.join(', ');
    card.innerHTML = `
      <p><strong>With ${m.with_team}</strong>: get ${names}</p>
      <p class="reason">Positions: ${positions} — Edge: ${m.edge_pct >= 0 ? '+' : ''}${m.edge_pct}%${
      m.noticeable_upgrade ? ' (noticeable upgrade)' : ''
    }</p>
    `;
    const btn = document.createElement('button');
    btn.textContent = 'Load into Team B';
    btn.addEventListener('click', () => loadPackageIntoTeamB(m));
    card.appendChild(btn);
    container.appendChild(card);
  });
}

function loadPackageIntoTeamB(match) {
  const theirTeam = state.teams.find((t) => t.team_name === match.with_team);
  if (!theirTeam) return;
  $('#team-b-select').value = theirTeam.roster_id;
  loadTradeSide('b').then(() => {
    match.get.forEach((p) => {
      const cb = $(`#team-b-players input[value="${p.player_id}"]`);
      if (cb) cb.checked = true;
    });
  });
}

function renderTradeResult(result) {
  const el = $('#trade-result');
  const verdictClass = result.verdict.replace(' ', '-');
  el.innerHTML = `
    <div class="verdict ${verdictClass}">
      <strong>${result.verdict.toUpperCase()}</strong> — gap ${result.gap_pct}%
      ${result.favors ? `(favors Team ${result.favors.toUpperCase()})` : ''}
    </div>
    <p>Team A total: ${result.side_a_total} &nbsp; Team B total: ${result.side_b_total}</p>
    ${result.unvalued_players.length ? `<p class="warn">Could not value: ${result.unvalued_players.join(', ')}</p>` : ''}
  `;
}

// ---------- Recommendations ----------

function preloadTradeMulti(myPlayerIds, theirTeamLabel, theirPlayerIds) {
  showTab('trade');
  $('#team-a-select').value = state.myRosterId;
  loadTradeSide('a').then(() => {
    myPlayerIds.forEach((id) => {
      const cb = $(`#team-a-players input[value="${id}"]`);
      if (cb) cb.checked = true;
    });
  });

  const theirTeam = state.teams.find((t) => t.team_name === theirTeamLabel);
  if (theirTeam) {
    $('#team-b-select').value = theirTeam.roster_id;
    loadTradeSide('b').then(() => {
      theirPlayerIds.forEach((id) => {
        const cb = $(`#team-b-players input[value="${id}"]`);
        if (cb) cb.checked = true;
      });
    });
  }
}

function preloadTrade(myPlayerId, theirRosterLabel, theirPlayerId) {
  preloadTradeMulti([myPlayerId], theirRosterLabel, [theirPlayerId]);
}

async function loadRecommendations() {
  const data = await api(withDynastyParam(`/api/league/${state.leagueId}/roster/${state.myRosterId}/recommendations`));

  const summary = $('#needs-summary');
  summary.innerHTML = '<h3>Positional Needs vs. League Average</h3>';
  const table = document.createElement('table');
  table.innerHTML = '<thead><tr><th>Position</th><th>Need Score</th><th>Surplus Score</th></tr></thead>';
  const tbody = document.createElement('tbody');
  Object.entries(data.needs_summary).forEach(([pos, scores]) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${pos}</td><td>${scores.need_score}</td><td>${scores.surplus_score}</td>`;
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  summary.appendChild(table);

  const suggestions = $('#suggestions');
  suggestions.innerHTML = '<h3>Suggested Trades</h3>';
  if (data.suggestions.length === 0) {
    suggestions.innerHTML += '<p>No clear complementary trades found right now.</p>';
    return;
  }
  data.suggestions.forEach((s) => {
    const card = document.createElement('div');
    card.className = 'suggestion-card';
    card.innerHTML = `
      <p><strong>With ${s.with_team}</strong>: give ${s.give.name} (${s.give.position}, ${s.give.value})
      for ${s.get.name} (${s.get.position}, ${s.get.value})</p>
      <p class="reason">${s.reason}</p>
      <p>Verdict: ${s.verdict.verdict} (gap ${s.verdict.gap_pct}%)</p>
    `;
    const btn = document.createElement('button');
    btn.textContent = 'Load into Trade Calculator';
    btn.addEventListener('click', () => preloadTrade(s.give.player_id, s.with_team, s.get.player_id));
    card.appendChild(btn);
    suggestions.appendChild(card);
  });
}

// ---------- Shop My Players ----------

async function loadShopPlayers() {
  const roster = await api(withDynastyParam(`/api/league/${state.leagueId}/roster/${state.myRosterId}/valued`));
  const container = $('#my-shop-players');
  container.innerHTML = '';
  roster.players.forEach((p) => {
    const label = document.createElement('label');
    label.className = 'player-checkbox';
    label.innerHTML = `<input type="checkbox" value="${p.player_id}"> ${p.name} (${p.position}, ${p.value})`;
    container.appendChild(label);
  });
}

$('#find-shop-matches-btn').addEventListener('click', async () => {
  const player_ids = Array.from($('#my-shop-players').querySelectorAll('input:checked')).map((el) => el.value);
  const shopMatches = $('#shop-matches');
  if (player_ids.length === 0) {
    shopMatches.innerHTML = '<p class="warn">Select at least one player to shop.</p>';
    return;
  }

  const favor_min_pct = parseFloat($('#favor-min').value) || 0;
  const favor_max_pct = parseFloat($('#favor-max').value) || 0;

  const data = await api(withDynastyParam(`/api/league/${state.leagueId}/roster/${state.myRosterId}/shop`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ player_ids, favor_min_pct, favor_max_pct }),
  });
  renderShopMatches(data.matches);
});

function renderShopMatches(matches) {
  const el = $('#shop-matches');
  el.innerHTML = '';
  if (matches.length === 0) {
    el.innerHTML = '<p>No matches found in that favor range — try widening it.</p>';
    return;
  }
  matches.forEach((m) => {
    const card = document.createElement('div');
    card.className = 'suggestion-card';
    const giveNames = m.give.map((p) => `${p.name} (${p.value})`).join(' + ');
    const getNames = m.get.map((p) => `${p.name} (${p.value})`).join(' + ');
    card.innerHTML = `
      <p><strong>With ${m.with_team}</strong>: give ${giveNames} for ${getNames}</p>
      <p class="reason">Edge in your favor: +${m.edge_pct}% (give ${m.give_total}, get ${m.get_total})</p>
    `;
    const btn = document.createElement('button');
    btn.textContent = 'Load into Trade Calculator';
    btn.addEventListener('click', () =>
      preloadTradeMulti(m.give.map((p) => p.player_id), m.with_team, m.get.map((p) => p.player_id))
    );
    card.appendChild(btn);
    el.appendChild(card);
  });
}

// ---------- League Intel ----------

async function loadLeagueAnalysis() {
  const data = await api(withDynastyParam(`/api/league/${state.leagueId}/analysis`));
  renderLeagueTeams(data.teams);
}

function renderLeagueTeams(teams) {
  const positions = ['QB', 'RB', 'WR', 'TE'];
  const container = $('#league-teams');
  const table = document.createElement('table');
  table.innerHTML = `<thead><tr><th>Team</th><th>Total Value</th>${positions
    .map((p) => `<th>${p} Need / Surplus</th>`)
    .join('')}</tr></thead>`;
  const tbody = document.createElement('tbody');
  teams.forEach((t) => {
    const tr = document.createElement('tr');
    if (t.roster_id === state.myRosterId) tr.classList.add('my-team-row');
    const posCells = positions
      .map((p) => `<td>${t.needs[p].need_score} / ${t.needs[p].surplus_score}</td>`)
      .join('');
    tr.innerHTML = `<td>${t.team_name}${t.roster_id === state.myRosterId ? ' (me)' : ''}</td><td>${t.total_value}</td>${posCells}`;
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  container.innerHTML = '';
  container.appendChild(table);
}

$('#load-waivers-btn').addEventListener('click', async () => {
  const position = $('#waiver-position').value;
  const qs = position ? `?position=${encodeURIComponent(position)}` : '';
  const data = await api(withDynastyParam(`/api/league/${state.leagueId}/roster/${state.myRosterId}/waivers${qs}`));
  renderWaiverWire(data.candidates);
});

function renderWaiverWire(candidates) {
  const container = $('#waiver-wire');
  const table = document.createElement('table');
  table.innerHTML = `<thead><tr><th>Player</th><th>Pos</th><th>Team</th><th>Value</th>
    <th>30d Trend</th><th>Sleeper Adds (24h)</th><th>Worth It?</th><th>Drop Candidate</th></tr></thead>`;
  const tbody = document.createElement('tbody');
  candidates.forEach((c) => {
    const tr = document.createElement('tr');
    const verdictClass = c.worth_it.verdict.replace(/ /g, '-');
    const dropName = c.worth_it.drop_candidate ? c.worth_it.drop_candidate.name : '-';
    tr.innerHTML = `
      <td>${c.name}</td><td>${c.position}</td><td>${c.team || '-'}</td><td>${c.value}</td>
      <td>${c.trend_30_day ?? '-'}</td><td>${c.trending_add_count}</td>
      <td class="worth-${verdictClass}">${c.worth_it.verdict}${c.worth_it.edge_pct != null ? ` (${c.worth_it.edge_pct}%)` : ''}</td>
      <td>${dropName}</td>
    `;
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  container.innerHTML = '';
  container.appendChild(table);
}
