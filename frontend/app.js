const tokenKey = "arcana.token";
let token = localStorage.getItem(tokenKey);
let currentUser = null;
let activeTournamentId = null;
let allTournaments = [];
let userTournamentIds = new Set();

const qs = (selector) => document.querySelector(selector);
const qsa = (selector) => document.querySelectorAll(selector);

qsa("nav button").forEach((button) => {
  button.addEventListener("click", () => showView(button.dataset.view));
});

qsa('dialog button[value="cancel"]').forEach((button) => {
  button.addEventListener("click", (event) => {
    event.preventDefault();
    button.closest("dialog")?.close();
  });
});

qs("#refreshTournaments").addEventListener("click", loadAll);
qs("#tournamentSearchForm").addEventListener("submit", applyTournamentSearch);
qs("#clearTournamentSearch").addEventListener("click", clearTournamentSearch);
qs("#loginForm").addEventListener("submit", login);
qs("#registerForm").addEventListener("submit", register);
qs("#createTournamentForm").addEventListener("submit", createTournament);
qs("#registrationForm").addEventListener("submit", registerForTournament);
qs("#deckForm").addEventListener("submit", submitDecklist);
qs("#refundForm").addEventListener("submit", submitRefundRequest);
qs("#announcementForm").addEventListener("submit", submitAnnouncement);
qs("#penaltyForm").addEventListener("submit", submitPenalty);
qs("#pairingForm").addEventListener("submit", submitManualPairing);
qs("#confirmDeleteForm").addEventListener("submit", confirmDeleteTournament);
qs("#completeSandboxPayment").addEventListener("click", completeSandboxPayment);
qs("#startTournament").addEventListener("click", () => startTournament(activeTournamentId));
qs("#nextRound").addEventListener("click", () => nextRound(activeTournamentId));
qs("#closeTournament").addEventListener("click", () => closeTournament(activeTournamentId));
qs("#deleteTournament").addEventListener("click", () => deleteTournament(activeTournamentId));

qsa("[data-oauth]").forEach((button) => {
  button.addEventListener("click", async () => {
    const provider = button.dataset.oauth;
    const response = await api(`/auth/oauth/${provider}/login`);
    if (response.authorization_url) window.location.href = response.authorization_url;
  });
});

document.addEventListener("click", async (event) => {
  const action = event.target.closest("[data-action]");
  if (!action) return;
  const id = action.dataset.id;
  if (action.dataset.action === "open-register") {
    requireLogin();
    qs("#registrationForm [name=tournament_id]").value = id;
    qs("#registerDialog").showModal();
  }
  if (action.dataset.action === "open-deck") {
    requireLogin();
    qs("#deckForm [name=tournament_id]").value = id;
    qs("#deckDialog").showModal();
  }
  if (action.dataset.action === "checkout") {
    requireLogin();
    const provider = action.dataset.provider;
    const payment = await api(`/tournaments/${id}/checkout`, {
      method: "POST",
      body: { provider },
    });
    if (payment.checkout_url) window.location.href = payment.checkout_url;
  }
  if (action.dataset.action === "view-registrations") {
    requireLogin();
    await loadTournamentDetail(id);
  }
  if (action.dataset.action === "report-result") {
    const select = qs(`[data-result-for="${action.dataset.pairingId}"]`);
    const [match_wins_a, match_wins_b] = select.value.split("-").map(Number);
    await api(`/tournaments/${activeTournamentId}/pairings/${action.dataset.pairingId}/result`, {
      method: "PATCH",
      body: { match_wins_a, match_wins_b, draws: 0 },
    });
    await loadTournamentDetail(activeTournamentId);
    toast("Risultato salvato.");
  }
  if (action.dataset.action === "report-player-result") {
    const select = qs(`[data-result-for="${action.dataset.pairingId}"]`);
    const [match_wins_a, match_wins_b] = select.value.split("-").map(Number);
    await api(`/tournaments/${activeTournamentId}/pairings/${action.dataset.pairingId}/player-result`, {
      method: "PATCH",
      body: { match_wins_a, match_wins_b, draws: 0 },
    });
    await loadTournamentDetail(activeTournamentId);
    toast("Risultato inviato.");
  }
  if (action.dataset.action === "save-controls") {
    await saveTournamentControls();
  }
  if (action.dataset.action === "detail-tab") {
    showDetailPane(action.dataset.tab);
  }
  if (action.dataset.action === "set-checkin") {
    await api(
      `/tournaments/${activeTournamentId}/registrations/${action.dataset.registrationId}/check-in?checked_in=${action.dataset.checkedIn}`,
      { method: "PATCH" },
    );
    await loadTournamentDetail(activeTournamentId);
  }
  if (action.dataset.action === "set-drop") {
    await api(
      `/tournaments/${activeTournamentId}/registrations/${action.dataset.registrationId}/drop?dropped=${action.dataset.dropped}`,
      { method: "PATCH" },
    );
    await loadTournamentDetail(activeTournamentId);
  }
  if (action.dataset.action === "export-standings") {
    exportStandingsCsv();
  }
  if (action.dataset.action === "export-registrations") {
    exportRegistrationsCsv();
  }
  if (action.dataset.action === "export-decklists") {
    exportDecklistsTxt();
  }
  if (action.dataset.action === "export-eventlink") {
    exportEventLinkCsv();
  }
  if (action.dataset.action === "view-player-deck") {
    const registration = window.activeTournamentCache?.registrations?.find(
      (item) => String(item.id) === String(action.dataset.registrationId),
    );
    if (registration) await openDeckView(registration);
  }
  if (action.dataset.action === "self-checkin") {
    await api(`/tournaments/${activeTournamentId}/self-check-in`, { method: "PATCH" });
    await loadTournamentDetail(activeTournamentId);
    toast("Check-in effettuato.");
  }
  if (action.dataset.action === "request-refund") {
    qs("#refundDialog").showModal();
  }
  if (action.dataset.action === "create-announcement") {
    qs("#announcementDialog").showModal();
  }
  if (action.dataset.action === "create-penalty") {
    qs("#penaltyForm [name=registration_id]").value = action.dataset.registrationId;
    qs("#penaltyDialog").showModal();
  }
  if (action.dataset.action === "player-card") {
    await showPlayerCard(action.dataset.registrationId);
  }
  if (action.dataset.action === "manual-pairing") {
    const pairing = findPairing(action.dataset.pairingId);
    qs("#pairingForm [name=pairing_id]").value = action.dataset.pairingId;
    qs("#pairingForm [name=table_number]").value = pairing?.table_number || 1;
    qs("#pairingForm [name=player_a_registration_id]").value = pairing?.player_a_registration_id || "";
    qs("#pairingForm [name=player_b_registration_id]").value = pairing?.player_b_registration_id || "";
    qs("#pairingDialog").showModal();
  }
  if (action.dataset.action === "show-bracket") {
    await showBracket();
  }
  if (action.dataset.action === "decide-refund") {
    await api(`/tournaments/${activeTournamentId}/payments/${action.dataset.paymentId}/refund`, {
      method: "POST",
      body: { approve: action.dataset.approve === "true" },
    });
    await loadTournamentDetail(activeTournamentId);
    toast(action.dataset.approve === "true" ? "Rimborso approvato." : "Rimborso respinto.");
  }
});

init();

async function init() {
  const url = new URL(window.location.href);
  const oauthToken = url.searchParams.get("token");
  const sandboxPaymentId = url.searchParams.get("payment_id");
  const sandboxProvider = url.searchParams.get("provider");
  if (oauthToken) {
    token = oauthToken;
    localStorage.setItem(tokenKey, token);
    url.searchParams.delete("token");
    window.history.replaceState({}, "", url.pathname);
  }
  if (window.location.pathname === "/sandbox-checkout" && sandboxPaymentId) {
    qs("#completeSandboxPayment").dataset.paymentId = sandboxPaymentId;
    qs("#sandboxCopy").textContent = `Checkout ${sandboxProvider || "sandbox"} pronto. Conferma per simulare il pagamento riuscito.`;
    showView("sandbox");
  } else {
    document.querySelector("[data-view=discover]").classList.add("active");
  }
  await loadMe();
  await loadAll();
  qs("#createTournamentForm [name=starts_on]").value = new Date().toISOString().slice(0, 10);
}

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(`/api${path}`, {
    ...options,
    headers,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  const isJson = response.headers.get("content-type")?.includes("application/json");
  const payload = isJson ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = typeof payload === "object" ? payload.detail : payload;
    toast(Array.isArray(detail) ? detail[0]?.msg : detail || "Errore richiesta");
    throw new Error(JSON.stringify(payload));
  }
  return payload;
}

async function loadMe() {
  if (!token) {
    currentUser = null;
    renderAccount();
    return;
  }
  try {
    currentUser = await api("/auth/me");
  } catch {
    localStorage.removeItem(tokenKey);
    token = null;
    currentUser = null;
  }
  renderAccount();
}

async function loadAll() {
  try {
    allTournaments = await api("/tournaments");
    let mine = [];
    if (token) {
      mine = await api("/tournaments/mine");
      renderProfileEvents(mine);
    }
    userTournamentIds = new Set(mine.map((tournament) => tournament.id));
    await applyTournamentSearch();
  } catch (error) {
    qs("#tournamentList").innerHTML = `<p class="muted">Impossibile caricare i tornei. Controlla il backend.</p>`;
    throw error;
  }
}

async function applyTournamentSearch(event) {
  event?.preventDefault();
  const filters = formData(qs("#tournamentSearchForm"));
  let tournaments = allTournaments.filter((tournament) => tournamentMatchesFilters(tournament, filters));
  const radiusKm = Number(filters.distance_km || 0);
  if (filters.distance_origin && radiusKm > 0) {
    tournaments = await filterByDistance(tournaments, filters.distance_origin, radiusKm);
  }
  renderTournamentList(qs("#tournamentList"), tournaments, false, userTournamentIds);
}

function clearTournamentSearch() {
  qs("#tournamentSearchForm").reset();
  renderTournamentList(qs("#tournamentList"), allTournaments, false, userTournamentIds);
}

function tournamentMatchesFilters(tournament, filters) {
  const name = normalizeSearch(filters.name);
  const venue = normalizeSearch(filters.venue);
  const tournamentDate = tournament.starts_on;
  if (name && !normalizeSearch(tournament.name).includes(name)) return false;
  if (venue && !normalizeSearch(tournament.venue || "").includes(venue)) return false;
  if (filters.date_from && tournamentDate < filters.date_from) return false;
  if (filters.date_to && tournamentDate > filters.date_to) return false;
  return true;
}

async function filterByDistance(tournaments, originText, radiusKm) {
  const origin = await geocodePlace(originText);
  if (!origin) {
    toast("Luogo di partenza non trovato.");
    return tournaments;
  }
  const filtered = [];
  for (const tournament of tournaments) {
    const venue = tournament.venue || "";
    if (!venue || venue.toLowerCase().includes("definire")) continue;
    const point = await geocodePlace(venue);
    if (!point) continue;
    const distance = distanceKm(origin, point);
    if (distance <= radiusKm) {
      filtered.push({ ...tournament, distance_km: distance });
    }
  }
  return filtered.sort((a, b) => (a.distance_km ?? 999999) - (b.distance_km ?? 999999));
}

async function geocodePlace(query) {
  const key = `arcana.geocode.${normalizeSearch(query)}`;
  const cached = localStorage.getItem(key);
  if (cached) return JSON.parse(cached);
  try {
    const url = new URL("https://nominatim.openstreetmap.org/search");
    url.searchParams.set("format", "json");
    url.searchParams.set("limit", "1");
    url.searchParams.set("q", query);
    const response = await fetch(url, { headers: { Accept: "application/json" } });
    if (!response.ok) return null;
    const [first] = await response.json();
    if (!first) return null;
    const point = { lat: Number(first.lat), lon: Number(first.lon) };
    localStorage.setItem(key, JSON.stringify(point));
    return point;
  } catch {
    toast("Ricerca distanza non disponibile.");
    return null;
  }
}

function distanceKm(a, b) {
  const radius = 6371;
  const dLat = toRad(b.lat - a.lat);
  const dLon = toRad(b.lon - a.lon);
  const lat1 = toRad(a.lat);
  const lat2 = toRad(b.lat);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return radius * 2 * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h));
}

function toRad(value) {
  return (value * Math.PI) / 180;
}

function normalizeSearch(value) {
  return String(value || "").trim().toLowerCase();
}

async function login(event) {
  event.preventDefault();
  const data = formData(event.target);
  const response = await api("/auth/login", { method: "POST", body: data });
  token = response.access_token;
  localStorage.setItem(tokenKey, token);
  event.target.reset();
  await loadMe();
  try {
    await loadAll();
  } catch {
    // The profile should still open even if the tournament feed is temporarily unavailable.
  }
  toast("Login effettuato.");
  showView("account");
}

async function register(event) {
  event.preventDefault();
  const data = formData(event.target);
  const response = await api("/auth/register", { method: "POST", body: data });
  token = response.access_token;
  localStorage.setItem(tokenKey, token);
  event.target.reset();
  await loadMe();
  try {
    await loadAll();
  } catch {
    // The profile should still open even if the tournament feed is temporarily unavailable.
  }
  toast("Account creato.");
  showView("account");
}

async function createTournament(event) {
  event.preventDefault();
  requireLogin();
  const data = formData(event.target);
  data.capacity = Number(data.capacity);
  data.entry_fee_cents = Math.round(Number(data.entry_fee) * 100);
  data.swiss_rounds = Number(data.swiss_rounds || 0);
  data.top_cut_size = Number(data.top_cut_size || 8);
  data.round_timer_minutes = Number(data.round_timer_minutes || 50);
  data.decklist_deadline = data.decklist_deadline ? new Date(data.decklist_deadline).toISOString() : null;
  delete data.entry_fee;
  data.decklist_required = Boolean(data.decklist_required);
  data.check_in_required = Boolean(data.check_in_required);
  data.self_check_in_enabled = Boolean(data.self_check_in_enabled);
  data.late_registration_enabled = Boolean(data.late_registration_enabled);
  data.pairings_public = Boolean(data.pairings_public);
  data.standings_public = Boolean(data.standings_public);
  data.email_notifications_enabled = Boolean(data.email_notifications_enabled);
  data.legal_validation_enabled = Boolean(data.legal_validation_enabled);
  await api("/tournaments", { method: "POST", body: data });
  event.target.reset();
  await loadAll();
  toast("Torneo creato.");
  showView("account");
}

async function registerForTournament(event) {
  event.preventDefault();
  const data = formData(event.target);
  const tournamentId = data.tournament_id;
  const paymentProvider = data.payment_provider || "stripe";
  delete data.tournament_id;
  delete data.payment_provider;
  await api(`/tournaments/${tournamentId}/registrations`, { method: "POST", body: data });
  qs("#registerDialog").close();
  await loadAll();
  toast("Iscrizione completata. Apertura pagamento.");
  const payment = await api(`/tournaments/${tournamentId}/checkout`, {
    method: "POST",
    body: { provider: paymentProvider },
  });
  if (payment.checkout_url) window.location.href = payment.checkout_url;
}

async function submitDecklist(event) {
  event.preventDefault();
  const data = formData(event.target);
  const tournamentId = data.tournament_id;
  await api(`/tournaments/${tournamentId}/decklist`, {
    method: "POST",
    body: { raw_text: data.raw_text, archetype: data.archetype || "" },
  });
  qs("#deckDialog").close();
  event.target.reset();
  await loadAll();
  toast("Decklist inviata.");
}

function renderTournamentList(container, tournaments, mine, userTournamentIds = new Set()) {
  if (!tournaments.length) {
    container.innerHTML = `<p class="muted">Nessun torneo trovato.</p>`;
    return;
  }
  container.innerHTML = tournaments
    .map((tournament) => tournamentRow(tournament, mine, userTournamentIds.has(tournament.id)))
    .join("");
}

function renderProfileEvents(tournaments) {
  const container = qs("#profileEventsList");
  if (!container) return;
  if (!tournaments.length) {
    container.innerHTML = `<p class="muted">Nessun torneo trovato.</p>`;
    return;
  }
  const today = new Date().toISOString().slice(0, 10);
  const current = tournaments.filter((item) => item.starts_on >= today && item.status !== "completed");
  const past = tournaments.filter((item) => item.starts_on < today || item.status === "completed");
  container.innerHTML = `
    <div class="wide">
      <h3>Attuali</h3>
      <div class="event-list">${current.length ? cardList(current, true) : `<p class="muted">Nessun torneo attuale.</p>`}</div>
      <h3>Passati</h3>
      <div class="event-list">${past.length ? cardList(past, true) : `<p class="muted">Nessun torneo passato.</p>`}</div>
    </div>
  `;
}

function cardList(tournaments, mine) {
  return tournaments
    .map((tournament) => tournamentRow(tournament, mine, true))
    .join("");
}

function tournamentRow(tournament, mine, alreadyJoined = false) {
  return `
    <article class="event-row">
      <div class="event-main">
        <span class="badge ${tournament.status === "published" ? "ok" : "warn"}">${escapeHtml(tournament.status)}</span>
        <div class="event-title">
          <h3>${escapeHtml(tournament.name)}</h3>
          ${mine && tournament.description ? `<small>${escapeHtml(tournament.description)}</small>` : ""}
        </div>
        <div class="event-meta">
          <span>${escapeHtml(tournament.format)} - ${escapeHtml(tournament.rules_enforcement_level)}</span>
          <span>${escapeHtml(tournament.venue || "Venue da definire")}</span>
          <span>${new Date(tournament.starts_on).toLocaleDateString("it-IT")} - ${money(tournament.entry_fee_cents, tournament.currency)}</span>
          <span>${tournament.registered_players}/${tournament.capacity} iscritti</span>
          ${tournament.distance_km ? `<span>${tournament.distance_km.toFixed(1)} km</span>` : ""}
        </div>
      </div>
      <div class="event-actions">
        ${
          alreadyJoined
            ? `<span class="badge ok">Gia iscritto</span>`
            : `<button class="primary" data-action="open-register" data-id="${tournament.id}">Iscriviti</button>`
        }
        <button class="secondary" data-action="open-deck" data-id="${tournament.id}">Decklist</button>
        <button class="secondary" data-action="view-registrations" data-id="${tournament.id}">Dettagli</button>
        ${organizerButton(tournament)}
      </div>
    </article>
  `;
}

async function loadTournamentDetail(tournamentId) {
  activeTournamentId = tournamentId;
  const tournament = await api(`/tournaments/${tournamentId}`);
  const isOrganizer = currentUser?.role === "organizer" && tournament.organizer_id === currentUser.id;
  const [registrations, standings, rounds] = await Promise.all([
    isOrganizer ? api(`/tournaments/${tournamentId}/registrations`) : Promise.resolve([]),
    api(`/tournaments/${tournamentId}/standings`),
    api(`/tournaments/${tournamentId}/rounds`),
  ]);
  const myRegistration = currentUser && !isOrganizer ? await api(`/tournaments/${tournamentId}/my-registration`).catch(() => null) : null;
  window.activeTournamentCache = { tournament, registrations, standings, rounds, myRegistration };
  qs("#detailTitle").textContent = tournament.name;
  qs("#startTournament").hidden = !isOrganizer;
  qs("#nextRound").hidden = !isOrganizer;
  qs("#closeTournament").hidden = !isOrganizer;
  qs("#deleteTournament").hidden = !isOrganizer;
  qs("#tournamentDetail").innerHTML = `
    <article class="panel">
      <div class="section-head">
        <div>
          <p class="eyebrow">${escapeHtml(tournament.structure)}</p>
          <h3>${escapeHtml(tournament.status)}</h3>
        </div>
        <span class="badge">${tournament.registered_players}/${tournament.capacity} iscritti</span>
      </div>
      <p>${escapeHtml(tournament.format)} - ${escapeHtml(tournament.rules_enforcement_level)}</p>
      <p>${escapeHtml(tournament.venue || "Venue da definire")}</p>
      <p>Deck deadline: ${tournament.decklist_deadline ? new Date(tournament.decklist_deadline).toLocaleString("it-IT") : "non impostata"}</p>
      <p>Timer round: ${tournament.round_timer_minutes} minuti</p>
      ${tournament.refund_policy ? `<p>Rimborsi: ${escapeHtml(tournament.refund_policy)}</p>` : ""}
      ${!isOrganizer && tournament.self_check_in_enabled ? `<button class="secondary" data-action="self-checkin">Check-in</button>` : ""}
      ${!isOrganizer ? `<button class="secondary" data-action="request-refund">Richiedi rimborso</button>` : ""}
    </article>
    ${isOrganizer ? renderTournamentControls(tournament) : ""}
    <div class="detail-tabs">
      <button class="detail-tab active" data-action="detail-tab" data-tab="overview">Classifica</button>
      <button class="detail-tab" data-action="detail-tab" data-tab="rounds">Turni</button>
      ${isOrganizer ? `<button class="detail-tab" data-action="detail-tab" data-tab="players">Iscritti</button>` : ""}
    </div>
    <div class="detail-pane active" data-pane="overview">${renderStandings(standings)}</div>
    <div class="detail-pane" data-pane="rounds">${renderRounds(rounds)}</div>
    ${isOrganizer ? `<div class="detail-pane" data-pane="players">${renderRegistrations(registrations)}</div>` : ""}
  `;
  showView("detail");
}

async function saveTournamentControls() {
  const form = qs("#tournamentControls");
  const data = formData(form);
  data.round_timer_minutes = Number(data.round_timer_minutes || 50);
  data.decklist_deadline = data.decklist_deadline ? new Date(data.decklist_deadline).toISOString() : null;
  data.self_check_in_enabled = Boolean(data.self_check_in_enabled);
  data.late_registration_enabled = Boolean(data.late_registration_enabled);
  data.pairings_public = Boolean(data.pairings_public);
  data.standings_public = Boolean(data.standings_public);
  data.email_notifications_enabled = Boolean(data.email_notifications_enabled);
  data.legal_validation_enabled = Boolean(data.legal_validation_enabled);
  await api(`/tournaments/${activeTournamentId}/controls`, { method: "PATCH", body: data });
  await loadTournamentDetail(activeTournamentId);
  await loadAll();
  toast("Controlli aggiornati.");
}

function renderTournamentControls(tournament) {
  return `
    <article class="panel">
      <div class="section-head">
        <div>
          <p class="eyebrow">Tournament controller</p>
          <h3>Controlli evento</h3>
        </div>
        <button class="primary" data-action="save-controls">Salva controlli</button>
      </div>
      <div class="form-grid compact-form" id="tournamentControls">
        <label>
          Deadline decklist
          <input name="decklist_deadline" type="datetime-local" value="${datetimeLocalValue(tournament.decklist_deadline)}" />
        </label>
        <label>
          Modalita iscrizione
          <select name="registration_mode">
            ${["open", "closed"].map((mode) => `<option value="${mode}" ${mode === tournament.registration_mode ? "selected" : ""}>${mode}</option>`).join("")}
          </select>
        </label>
        <label>
          Timer round
          <input name="round_timer_minutes" min="1" max="120" type="number" value="${tournament.round_timer_minutes}" />
        </label>
        <label>
          Policy rimborsi
          <input name="refund_policy" value="${escapeHtml(tournament.refund_policy || "")}" />
        </label>
        <label class="check"><input name="self_check_in_enabled" type="checkbox" ${tournament.self_check_in_enabled ? "checked" : ""} /> Self check-in</label>
        <label class="check"><input name="late_registration_enabled" type="checkbox" ${tournament.late_registration_enabled ? "checked" : ""} /> Late registration</label>
        <label class="check"><input name="pairings_public" type="checkbox" ${tournament.pairings_public ? "checked" : ""} /> Pairings pubblici</label>
        <label class="check"><input name="standings_public" type="checkbox" ${tournament.standings_public ? "checked" : ""} /> Classifica pubblica</label>
        <label class="check"><input name="email_notifications_enabled" type="checkbox" ${tournament.email_notifications_enabled ? "checked" : ""} /> Notifiche email</label>
        <label class="check"><input name="legal_validation_enabled" type="checkbox" ${tournament.legal_validation_enabled ? "checked" : ""} /> Validazione Scryfall</label>
        <div class="row wide">
          <button class="secondary" type="button" data-action="create-announcement">Annuncio</button>
          <button class="secondary" type="button" data-action="show-bracket">Bracket top cut</button>
        </div>
      </div>
    </article>
  `;
}

function renderRegistrations(registrations) {
  return `
    <section>
      <div class="section-head">
        <h3>Iscritti</h3>
        <div class="row">
          <button class="secondary" data-action="export-registrations">Esporta iscritti CSV</button>
          <button class="secondary" data-action="export-eventlink">Export EventLink CSV</button>
          <button class="secondary" data-action="export-decklists">Esporta decklist</button>
        </div>
      </div>
      <div class="registration-list">
        ${
          registrations.length
    ? registrations
        .map(
          (registration) => `
            <article class="panel registration-card">
              <div class="section-head">
                <div>
                  <h3>${escapeHtml(registration.player.display_name)}</h3>
                  <p class="muted">${escapeHtml(registration.player_email)}</p>
                </div>
                <div class="row">
                  <span class="badge ${registration.payment_status === "paid" ? "ok" : "warn"}">${escapeHtml(registration.payment_status)}</span>
                  <span class="badge ${registration.decklist_status === "valid" ? "ok" : "warn"}">${escapeHtml(registration.decklist_status)}</span>
                  <span class="badge ${registration.checked_in ? "ok" : "warn"}">${registration.checked_in ? "check-in" : "no check-in"}</span>
                  ${registration.dropped ? `<span class="badge warn">drop</span>` : ""}
                </div>
              </div>
              <p>Archetipo: ${escapeHtml(registration.archetype || "Non dichiarato")}</p>
              <p>Wizards Account: ${escapeHtml(registration.wizards_account || "N/D")}</p>
              <p>Main ${registration.decklist_main_count ?? "-"} / Side ${registration.decklist_side_count ?? "-"}</p>
              ${
                registration.decklist_errors
                  ? `<p class="badge warn">${escapeHtml(registration.decklist_errors)}</p>`
                  : ""
              }
              <div class="row">
                <button class="secondary" data-action="view-player-deck" data-registration-id="${registration.id}">
                  Vedi decklist
                </button>
                <button class="secondary" data-action="player-card" data-registration-id="${registration.id}">
                  Player card
                </button>
                <button class="secondary" data-action="create-penalty" data-registration-id="${registration.id}">
                  Penalita
                </button>
                ${
                  registration.payment_status === "refund_requested" && registration.payment_id
                    ? `
                      <button class="secondary" data-action="decide-refund" data-payment-id="${registration.payment_id}" data-approve="true">Approva rimborso</button>
                      <button class="secondary" data-action="decide-refund" data-payment-id="${registration.payment_id}" data-approve="false">Rifiuta rimborso</button>
                    `
                    : ""
                }
                <button class="secondary" data-action="set-checkin" data-registration-id="${registration.id}" data-checked-in="${!registration.checked_in}">
                  ${registration.checked_in ? "Annulla check-in" : "Check-in"}
                </button>
                <button class="secondary" data-action="set-drop" data-registration-id="${registration.id}" data-dropped="${!registration.dropped}">
                  ${registration.dropped ? "Riammetti" : "Drop"}
                </button>
              </div>
            </article>
          `,
        )
        .join("")
    : `<p class="muted">Nessun iscritto per questo torneo.</p>`
        }
      </div>
    </section>
  `;
}

function renderStandings(standings) {
  return `
    <section class="panel">
      <div class="section-head">
        <h3>Classifica</h3>
        <button class="secondary" data-action="export-standings">Esporta CSV</button>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Posizione</th>
              <th>Nome</th>
              <th>Punti</th>
              <th>V/S/P</th>
              <th>%VIA</th>
              <th>%VP</th>
              <th>%VPA</th>
            </tr>
          </thead>
          <tbody>
            ${
              standings.length
                ? standings
                    .map(
                      (row) => `
                        <tr>
                          <td>${row.position}</td>
                          <td><strong>${escapeHtml(row.name)}</strong></td>
                          <td>${row.points}</td>
                          <td>${escapeHtml(row.record)}</td>
                          <td>${row.opponent_match_win_percentage.toFixed(1)}%</td>
                          <td>${row.game_win_percentage.toFixed(1)}%</td>
                          <td>${row.opponent_game_win_percentage.toFixed(1)}%</td>
                        </tr>
                      `,
                    )
                    .join("")
                : `<tr><td colspan="7" class="muted">La classifica apparira dopo lo start.</td></tr>`
            }
          </tbody>
        </table>
      </div>
    </section>
  `;
}

function renderRounds(rounds) {
  return `
    <section>
      <h3>Turni e pairings</h3>
      <div class="round-panel">
        ${
          rounds.length
            ? rounds
                .map(
                  (round) => `
                    <article class="panel">
                      <div class="section-head">
                        <h3>Turno ${round.number}</h3>
                        <span class="badge">${escapeHtml(round.phase)}</span>
                      </div>
                      ${round.pairings
                        .map(
                          (pairing) => `
                            <div class="pairing-row">
                              <strong>Tavolo ${pairing.table_number}</strong>
                              <span>${escapeHtml(pairing.player_a)} vs ${escapeHtml(pairing.player_b || "BYE")}</span>
                              ${round.ends_at ? `<span class="muted">${new Date(round.ends_at).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" })}</span>` : ""}
                              ${pairing.player_b ? resultControl(pairing) : `<span class="badge ok">BYE</span>`}
                            </div>
                          `,
                        )
                        .join("")}
                    </article>
                  `,
                )
                .join("")
            : `<p class="muted">Nessun turno creato.</p>`
        }
      </div>
    </section>
  `;
}

function resultControl(pairing) {
  const current = pairing.result ? `${pairing.match_wins_a}-${pairing.match_wins_b}` : "2-0";
  const isOrganizer = currentUser?.role === "organizer" && window.activeTournamentCache?.tournament?.organizer_id === currentUser.id;
  const canReportAsPlayer = [pairing.player_a_registration_id, pairing.player_b_registration_id].includes(
    window.activeTournamentCache?.myRegistration?.id,
  );
  if (!isOrganizer && !canReportAsPlayer) {
    return pairing.result ? `<span class="badge">${current}</span>` : `<span class="badge warn">In attesa</span>`;
  }
  return `
    <span class="row">
      <select data-result-for="${pairing.id}">
        ${["0-0", "1-0", "1-1", "0-1", "2-0", "0-2", "2-1", "1-2"].map(
          (value) => `<option value="${value}" ${value === current ? "selected" : ""}>${value}</option>`,
        ).join("")}
      </select>
      <button class="secondary" data-action="${isOrganizer ? "report-result" : "report-player-result"}" data-pairing-id="${pairing.id}">Salva</button>
      ${isOrganizer && !pairing.result ? `<button class="secondary" data-action="manual-pairing" data-pairing-id="${pairing.id}">Modifica pairing</button>` : ""}
    </span>
  `;
}

function showDetailPane(tab) {
  qsa(".detail-tab").forEach((button) => button.classList.toggle("active", button.dataset.tab === tab));
  qsa(".detail-pane").forEach((pane) => pane.classList.toggle("active", pane.dataset.pane === tab));
}

function exportStandingsCsv() {
  const standings = window.activeTournamentCache?.standings || [];
  const rows = [
    ["posizione", "nome", "punti", "v_s_p", "via", "vp", "vpa"],
    ...standings.map((row) => [
      row.position,
      row.name,
      row.points,
      row.record,
      row.opponent_match_win_percentage,
      row.game_win_percentage,
      row.opponent_game_win_percentage,
    ]),
  ];
  downloadText("classifica.csv", toCsv(rows), "text/csv");
}

function exportRegistrationsCsv() {
  const registrations = window.activeTournamentCache?.registrations || [];
  const rows = [
    ["nome", "email", "wizards", "archetipo", "pagamento", "decklist", "check_in", "drop"],
    ...registrations.map((registration) => [
      registration.player.display_name,
      registration.player_email,
      registration.wizards_account,
      registration.archetype,
      registration.payment_status,
      registration.decklist_status,
      registration.checked_in ? "yes" : "no",
      registration.dropped ? "yes" : "no",
    ]),
  ];
  downloadText("iscritti.csv", toCsv(rows), "text/csv");
}

function exportDecklistsTxt() {
  const registrations = window.activeTournamentCache?.registrations || [];
  const content = registrations
    .map(
      (registration) =>
        `# ${registration.player.display_name} - ${registration.archetype || "N/D"}\n${registration.decklist_raw_text || "Decklist non caricata."}`,
    )
    .join("\n\n---\n\n");
  downloadText("decklist.txt", content, "text/plain");
}

function exportEventLinkCsv() {
  const registrations = window.activeTournamentCache?.registrations || [];
  const rows = [
    ["First Name", "Last Name", "Email", "Wizards Account", "Archetype", "Paid", "Checked In"],
    ...registrations.map((registration) => {
      const parts = registration.player.display_name.trim().split(/\s+/);
      const first = parts.shift() || registration.player.display_name;
      const last = parts.join(" ");
      return [
        first,
        last,
        registration.player_email,
        registration.wizards_account,
        registration.archetype,
        registration.payment_status === "paid" ? "yes" : "no",
        registration.checked_in ? "yes" : "no",
      ];
    }),
  ];
  downloadText("eventlink-export.csv", toCsv(rows), "text/csv");
}

async function openDeckView(registration) {
  qs("#deckViewTitle").textContent = `${registration.player.display_name} - ${registration.archetype || "N/D"}`;
  const deck = parseDeckForImages(registration.decklist_raw_text || "");
  const allCards = [...deck.main, ...deck.side];
  qs("#deckImageGrid").innerHTML = allCards.length
    ? `
      <div class="deck-sections">
        <section class="deck-section">
          <h3>Main Deck</h3>
          <div class="card-image-grid">${deck.main.map((card) => renderCardTile(card)).join("")}</div>
        </section>
        <section class="deck-section">
          <h3>Sideboard</h3>
          <div class="card-image-grid sideboard-grid">${
            deck.side.length
              ? deck.side.map((card) => renderCardTile(card)).join("")
              : `<p class="muted">Sideboard non presente.</p>`
          }</div>
        </section>
      </div>
    `
    : `<p class="muted">Decklist non caricata.</p>`;
  qs("#deckViewDialog").showModal();
  if (allCards.length) await hydrateScryfallImages(allCards);
}

function parseDeckForImages(rawText) {
  const deck = { main: [], side: [] };
  let section = "main";
  for (const rawLine of rawText.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line) continue;
    if (/^(sideboard|side|sb)\b/i.test(line)) {
      section = "side";
      continue;
    }
    const match = line.match(/^(\d+)\s+(.+)$/);
    if (!match) continue;
    const quantity = Number(match[1]);
    const name = match[2].replace(/\s+\(.+\)$/, "").replace(/\s+\d+$/g, "").trim();
    deck[section].push({
      quantity,
      name,
      section,
      index: deck[section].length,
    });
  }
  return deck;
}

function renderCardTile(card) {
  const key = cardKey(card);
  return `
    <article class="card-tile fallback-card" data-card-key="${key}">
      <span class="card-qty">${card.quantity}</span>
      <div class="card-name-fallback">${escapeHtml(card.name)}</div>
    </article>
  `;
}

async function hydrateScryfallImages(cards) {
  try {
    const response = await fetch("https://api.scryfall.com/cards/collection", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ identifiers: cards.map((card) => ({ name: card.name })) }),
    });
    if (!response.ok) return;
    const payload = await response.json();
    for (const card of cards) {
      const found = findScryfallCard(payload.data, card.name);
      const image = imageForDeckCard(found, card.name);
      if (!image) continue;
      const tile = qs(`[data-card-key="${cardKey(card)}"]`);
      if (tile) {
        tile.classList.remove("fallback-card");
        tile.innerHTML = `<span class="card-qty">${card.quantity}</span><img alt="${escapeHtml(card.name)}" src="${image}" loading="lazy" />`;
      }
    }
  } catch {
    toast("Impossibile caricare immagini Scryfall.");
  }
}

function findScryfallCard(scryfallCards, deckName) {
  const normalizedDeckName = normalizeCardName(deckName);
  return scryfallCards.find((card) => {
    if (normalizeCardName(card.name) === normalizedDeckName) return true;
    if (card.card_faces?.some((face) => normalizeCardName(face.name) === normalizedDeckName)) {
      return true;
    }
    return normalizeCardName(card.name).split(" // ").includes(normalizedDeckName);
  });
}

function imageForDeckCard(scryfallCard, deckName) {
  if (!scryfallCard) return "";
  if (scryfallCard.image_uris?.normal || scryfallCard.image_uris?.small) {
    return scryfallCard.image_uris.normal || scryfallCard.image_uris.small;
  }
  const normalizedDeckName = normalizeCardName(deckName);
  const matchingFace = scryfallCard.card_faces?.find(
    (face) => normalizeCardName(face.name) === normalizedDeckName,
  );
  const face = matchingFace || scryfallCard.card_faces?.[0];
  return face?.image_uris?.normal || face?.image_uris?.small || "";
}

function normalizeCardName(name) {
  return String(name).trim().toLowerCase();
}

function cardKey(card) {
  return `${card.section}-${card.index}-${card.name.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
}

function toCsv(rows) {
  return rows.map((row) => row.map((cell) => `"${String(cell ?? "").replaceAll('"', '""')}"`).join(",")).join("\n");
}

function downloadText(filename, content, type) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

async function startTournament(tournamentId) {
  if (!tournamentId) return;
  await api(`/tournaments/${tournamentId}/start`, { method: "POST" });
  await loadTournamentDetail(tournamentId);
  await loadAll();
  toast("Torneo avviato.");
}

async function nextRound(tournamentId) {
  if (!tournamentId) return;
  await api(`/tournaments/${tournamentId}/rounds`, { method: "POST" });
  await loadTournamentDetail(tournamentId);
  toast("Nuovo turno creato.");
}

async function closeTournament(tournamentId) {
  if (!tournamentId) return;
  await api(`/tournaments/${tournamentId}/close`, { method: "POST" });
  await loadTournamentDetail(tournamentId);
  await loadAll();
  toast("Torneo chiuso.");
}

async function deleteTournament(tournamentId) {
  if (!tournamentId) return;
  qs("#confirmDeleteDialog").showModal();
}

async function confirmDeleteTournament(event) {
  event.preventDefault();
  const tournamentId = activeTournamentId;
  if (!tournamentId) return;
  await api(`/tournaments/${tournamentId}`, { method: "DELETE" });
  qs("#confirmDeleteDialog").close();
  activeTournamentId = null;
  await loadAll();
  showView("account");
  toast("Torneo cancellato.");
}

async function submitRefundRequest(event) {
  event.preventDefault();
  const data = formData(event.target);
  await api(`/tournaments/${activeTournamentId}/refund-request`, {
    method: "POST",
    body: { reason: data.reason || "" },
  });
  qs("#refundDialog").close();
  event.target.reset();
  await loadTournamentDetail(activeTournamentId);
  toast("Richiesta rimborso inviata.");
}

async function submitAnnouncement(event) {
  event.preventDefault();
  const data = formData(event.target);
  await api(`/tournaments/${activeTournamentId}/announcements`, {
    method: "POST",
    body: { title: data.title, body: data.body, send_email: Boolean(data.send_email) },
  });
  qs("#announcementDialog").close();
  event.target.reset();
  toast("Annuncio creato.");
}

async function submitPenalty(event) {
  event.preventDefault();
  const data = formData(event.target);
  await api(`/tournaments/${activeTournamentId}/penalties`, {
    method: "POST",
    body: {
      registration_id: Number(data.registration_id),
      round_id: data.round_id ? Number(data.round_id) : null,
      kind: data.kind,
      note: data.note || "",
      is_private: Boolean(data.is_private),
    },
  });
  qs("#penaltyDialog").close();
  event.target.reset();
  toast("Penalita registrata.");
}

async function showPlayerCard(registrationId) {
  const card = await api(`/tournaments/${activeTournamentId}/player-card/${registrationId}`);
  openInfoDialog(renderPlayerCard(card));
}

async function submitManualPairing(event) {
  event.preventDefault();
  const data = formData(event.target);
  await api(`/tournaments/${activeTournamentId}/pairings/${data.pairing_id}`, {
    method: "PATCH",
    body: {
      table_number: Number(data.table_number),
      player_a_registration_id: Number(data.player_a_registration_id),
      player_b_registration_id: data.player_b_registration_id ? Number(data.player_b_registration_id) : null,
    },
  });
  qs("#pairingDialog").close();
  await loadTournamentDetail(activeTournamentId);
  toast("Pairing aggiornato.");
}

async function showBracket() {
  const matches = await api(`/tournaments/${activeTournamentId}/bracket`);
  openInfoDialog(renderBracket(matches));
}

function openInfoDialog(html) {
  qs("#infoDialogContent").innerHTML = html;
  qs("#infoDialog").showModal();
}

function renderPlayerCard(card) {
  return `
    <div class="info-panel">
      <p class="eyebrow">Player card</p>
      <h2>${escapeHtml(card.registration.player.display_name)}</h2>
      <div class="stat-grid">
        <span><strong>Pagamento</strong>${escapeHtml(card.registration.payment_status)}</span>
        <span><strong>Decklist</strong>${escapeHtml(card.registration.decklist_status)}</span>
        <span><strong>Check-in</strong>${card.registration.checked_in ? "Si" : "No"}</span>
        <span><strong>Drop</strong>${card.registration.dropped ? "Si" : "No"}</span>
      </div>
      <h3>Match</h3>
      <div class="table-wrap compact-table">
        <table>
          <thead><tr><th>Tavolo</th><th>Giocatori</th><th>Risultato</th></tr></thead>
          <tbody>
            ${
              card.pairings.length
                ? card.pairings.map((pairing) => `
                  <tr>
                    <td>${pairing.table_number}</td>
                    <td>${escapeHtml(pairing.player_a)} vs ${escapeHtml(pairing.player_b || "BYE")}</td>
                    <td>${pairing.result ? `${pairing.match_wins_a}-${pairing.match_wins_b}` : "TBD"}</td>
                  </tr>
                `).join("")
                : `<tr><td colspan="3" class="muted">Nessun match.</td></tr>`
            }
          </tbody>
        </table>
      </div>
      <h3>Penalita</h3>
      ${
        card.penalties.length
          ? card.penalties.map((penalty) => `<p><span class="badge warn">${escapeHtml(penalty.kind)}</span> ${escapeHtml(penalty.note || "")}</p>`).join("")
          : `<p class="muted">Nessuna penalita.</p>`
      }
    </div>
  `;
}

function renderBracket(matches) {
  if (!matches.length) {
    return `
      <div class="info-panel">
        <p class="eyebrow">Bracket</p>
        <h2>Bracket non disponibile</h2>
        <p class="muted">Il bracket appare quando sono presenti round top cut o eliminazione.</p>
      </div>
    `;
  }
  const grouped = matches.reduce((acc, match) => {
    acc[match.round_number] ||= [];
    acc[match.round_number].push(match);
    return acc;
  }, {});
  const isOrganizer = currentUser?.role === "organizer" && window.activeTournamentCache?.tournament?.organizer_id === currentUser.id;
  return `
    <div class="info-panel">
      <p class="eyebrow">Bracket</p>
      <h2>Top cut / eliminazione</h2>
      <div class="bracket-board">
        ${Object.entries(grouped).map(([round, roundMatches]) => `
          <section class="bracket-column">
            <h3>Round ${round}</h3>
            ${roundMatches.map((match) => `
              <article class="bracket-match">
                <span>${escapeHtml(match.player_a)}</span>
                <span>${escapeHtml(match.player_b || "BYE")}</span>
                <strong>${escapeHtml(match.winner || "TBD")}</strong>
                ${
                  isOrganizer && match.player_b && !match.winner
                    ? `
                      <div class="bracket-result">
                        <select data-result-for="${match.pairing_id}">
                          ${["2-0", "2-1", "1-2", "0-2", "1-1", "1-0", "0-1", "0-0"].map(
                            (value) => `<option value="${value}">${value}</option>`,
                          ).join("")}
                        </select>
                        <button class="secondary" data-action="report-result" data-pairing-id="${match.pairing_id}">Salva</button>
                      </div>
                    `
                    : ""
                }
              </article>
            `).join("")}
          </section>
        `).join("")}
      </div>
    </div>
  `;
}

function findPairing(pairingId) {
  const rounds = window.activeTournamentCache?.rounds || [];
  for (const round of rounds) {
    const pairing = round.pairings.find((item) => String(item.id) === String(pairingId));
    if (pairing) return pairing;
  }
  return null;
}

async function completeSandboxPayment() {
  const paymentId = qs("#completeSandboxPayment").dataset.paymentId;
  if (!paymentId) return;
  await api(`/payments/sandbox/${paymentId}/complete`, { method: "POST" });
  toast("Pagamento sandbox completato.");
  window.history.replaceState({}, "", "/");
  await loadAll();
  showView("account");
}

function organizerButton(tournament) {
  if (!currentUser || currentUser.role !== "organizer" || tournament.organizer_id !== currentUser.id) {
    return "";
  }
  return `<button class="secondary" data-action="view-registrations" data-id="${tournament.id}">Gestisci</button>`;
}

function renderAccount() {
  qs("#accountNavButton").textContent = currentUser ? "Profilo" : "Login/Registrati";
  qs("#createNavButton").hidden = !currentUser || currentUser.role !== "organizer";
  if (!currentUser) {
    qs("#accountBox").innerHTML = "Non autenticato";
    qs("#accountTitle").textContent = "Login e registrazione";
    qs("#authForms").hidden = false;
    qs("#profilePanel").hidden = true;
    qs("#profilePanel").innerHTML = "";
    return;
  }
  qs("#accountBox").innerHTML = `
    <strong>${escapeHtml(currentUser.display_name)}</strong><br>
    <small>${escapeHtml(currentUser.email)}</small><br>
    <span class="badge">${escapeHtml(currentUser.role)}</span><br><br>
    <button class="secondary" id="logout">Logout</button>
  `;
  qs("#accountTitle").textContent = "Profilo";
  qs("#authForms").hidden = true;
  qs("#profilePanel").hidden = false;
  qs("#profilePanel").innerHTML = `
    <article class="panel">
      <h3>${escapeHtml(currentUser.display_name)}</h3>
      <p>${escapeHtml(currentUser.email)}</p>
      <span class="badge">${escapeHtml(currentUser.role)}</span>
    </article>
    <article class="panel">
      <div class="section-head">
        <div>
          <p class="eyebrow">Eventi</p>
          <h3>I tuoi tornei</h3>
        </div>
      </div>
      <div id="profileEventsList">
        <p class="muted">Caricamento eventi...</p>
      </div>
    </article>
  `;
  qs("#logout").addEventListener("click", () => {
    localStorage.removeItem(tokenKey);
    token = null;
    currentUser = null;
    renderAccount();
    loadAll();
    showView("discover");
  });
}

function showView(id) {
  if (id === "create" && (!currentUser || currentUser.role !== "organizer")) {
    id = "account";
  }
  qsa(".view").forEach((view) => view.classList.toggle("active", view.id === id));
  qsa("nav button").forEach((button) => button.classList.toggle("active", button.dataset.view === id));
}

function formData(form) {
  const data = Object.fromEntries(new FormData(form).entries());
  form.querySelectorAll("input[type=checkbox]").forEach((input) => {
    data[input.name] = input.checked;
  });
  return data;
}

function requireLogin() {
  if (!token) {
    showView("account");
    throw new Error("Login required");
  }
}

function money(cents, currency) {
  return new Intl.NumberFormat("it-IT", { style: "currency", currency }).format(cents / 100);
}

function datetimeLocalValue(value) {
  if (!value) return "";
  const date = new Date(value);
  const offset = date.getTimezoneOffset();
  const local = new Date(date.getTime() - offset * 60000);
  return local.toISOString().slice(0, 16);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function toast(message) {
  const element = qs("#toast");
  element.textContent = message;
  element.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => element.classList.remove("show"), 2400);
}
