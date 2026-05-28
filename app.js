const STORAGE_KEY = "arcana-events-state-v1";

const today = new Date().toISOString().slice(0, 10);

const seedState = {
  activeEventId: "event-rcq-modern",
  events: [
    {
      id: "event-rcq-modern",
      name: "RCQ Modern - Arcana Store",
      format: "Modern",
      date: today,
      capacity: 64,
      fee: 25,
      rel: "Competitive",
      notes: "Decklist obbligatorie entro inizio round 1. Cut Top 8.",
    },
  ],
  players: [
    {
      id: "p-1",
      eventId: "event-rcq-modern",
      name: "Luca Ferri",
      email: "luca@example.com",
      wizards: "1234567890",
      archetype: "Izzet Murktide",
      paid: true,
      paymentMethod: "Carta",
      paymentRef: "POS-1024",
      deck: sampleDeck(36, 24, 15, true),
    },
    {
      id: "p-2",
      eventId: "event-rcq-modern",
      name: "Sara Conti",
      email: "sara@example.com",
      wizards: "8844201199",
      archetype: "Yawgmoth",
      paid: false,
      paymentMethod: "",
      paymentRef: "",
      deck: sampleDeck(34, 26, 13, true),
    },
    {
      id: "p-3",
      eventId: "event-rcq-modern",
      name: "Marco Neri",
      email: "marco@example.com",
      wizards: "7712003391",
      archetype: "Domain Zoo",
      paid: true,
      paymentMethod: "PayPal",
      paymentRef: "PP-8891",
      deck: null,
    },
  ],
  rounds: [],
};

let state = loadState();
let pendingPaymentPlayerId = null;

const els = {
  eventSelect: document.querySelector("#eventSelect"),
  navTabs: document.querySelectorAll(".nav-tab"),
  viewButtons: document.querySelectorAll("[data-open-view]"),
  metricPlayers: document.querySelector("#metricPlayers"),
  metricCapacity: document.querySelector("#metricCapacity"),
  metricPaid: document.querySelector("#metricPaid"),
  metricRevenue: document.querySelector("#metricRevenue"),
  metricDecks: document.querySelector("#metricDecks"),
  metricMissingDecks: document.querySelector("#metricMissingDecks"),
  metricRounds: document.querySelector("#metricRounds"),
  metricNextRound: document.querySelector("#metricNextRound"),
  checklist: document.querySelector("#checklist"),
  attentionList: document.querySelector("#attentionList"),
  eventsTable: document.querySelector("#eventsTable"),
  playersTable: document.querySelector("#playersTable"),
  deckPlayer: document.querySelector("#deckPlayer"),
  deckFile: document.querySelector("#deckFile"),
  deckText: document.querySelector("#deckText"),
  deckTable: document.querySelector("#deckTable"),
  paymentCards: document.querySelector("#paymentCards"),
  roundsContainer: document.querySelector("#roundsContainer"),
  toast: document.querySelector("#toast"),
  paymentDialog: document.querySelector("#paymentDialog"),
  paymentTitle: document.querySelector("#paymentTitle"),
  paymentSummary: document.querySelector("#paymentSummary"),
  paymentMethod: document.querySelector("#paymentMethod"),
  paymentRef: document.querySelector("#paymentRef"),
};

document.querySelector("#eventForm").addEventListener("submit", createEvent);
document.querySelector("#playerForm").addEventListener("submit", createPlayer);
document.querySelector("#deckForm").addEventListener("submit", saveDecklist);
document.querySelector("#deckFile").addEventListener("change", readDeckFile);
document.querySelector("#generateRound").addEventListener("click", generateRound);
document.querySelector("#markAllPaid").addEventListener("click", markAllPaid);
document.querySelector("#confirmPayment").addEventListener("click", confirmPayment);
document.querySelector("#exportCsv").addEventListener("click", exportCsv);
document.querySelector("#printDecks").addEventListener("click", printDecks);
document.querySelector("#resetDemo").addEventListener("click", resetDemo);
els.eventSelect.addEventListener("change", (event) => {
  state.activeEventId = event.target.value;
  saveState();
  render();
});

els.navTabs.forEach((button) => {
  button.addEventListener("click", () => showView(button.dataset.view));
});

els.viewButtons.forEach((button) => {
  button.addEventListener("click", () => showView(button.dataset.openView));
});

document.addEventListener("click", (event) => {
  const action = event.target.closest("[data-action]");
  if (!action) return;
  const { action: type, id } = action.dataset;
  if (type === "select-event") selectEvent(id);
  if (type === "remove-player") removePlayer(id);
  if (type === "open-payment") openPayment(id);
  if (type === "toggle-paid") togglePaid(id);
  if (type === "remove-event") removeEvent(id);
  if (type === "view-deck") viewDeck(id);
});

render();

function loadState() {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (!saved) return structuredClone(seedState);
  try {
    return JSON.parse(saved);
  } catch {
    return structuredClone(seedState);
  }
}

function saveState() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

function activeEvent() {
  return state.events.find((event) => event.id === state.activeEventId) || state.events[0];
}

function activePlayers() {
  const event = activeEvent();
  return state.players.filter((player) => player.eventId === event.id);
}

function render() {
  const event = activeEvent();
  if (!event) return;
  const players = activePlayers();
  const paid = players.filter((player) => player.paid).length;
  const validDecks = players.filter((player) => player.deck?.valid).length;
  const revenue = paid * Number(event.fee || 0);
  const rounds = state.rounds.filter((round) => round.eventId === event.id);

  els.eventSelect.innerHTML = state.events
    .map((item) => `<option value="${item.id}">${escapeHtml(item.name)}</option>`)
    .join("");
  els.eventSelect.value = event.id;

  els.metricPlayers.textContent = players.length;
  els.metricCapacity.textContent = `${Math.max(event.capacity - players.length, 0)} posti disponibili`;
  els.metricPaid.textContent = percent(paid, players.length);
  els.metricRevenue.textContent = `${formatMoney(revenue)} incassati`;
  els.metricDecks.textContent = percent(validDecks, players.length);
  els.metricMissingDecks.textContent = `${Math.max(players.length - validDecks, 0)} mancanti o non valide`;
  els.metricRounds.textContent = rounds.length;
  els.metricNextRound.textContent = `Pronto per round ${rounds.length + 1}`;

  renderChecklist(event, players, paid, validDecks);
  renderAttention(players);
  renderEvents();
  renderPlayers(players);
  renderDecks(players);
  renderPayments(event, players);
  renderRounds(event);
  saveState();
}

function renderChecklist(event, players, paid, validDecks) {
  const checks = [
    ["Capienza configurata", event.capacity > 0],
    ["Almeno 8 iscritti consigliati", players.length >= 8],
    ["Tutti i pagamenti registrati", players.length > 0 && paid === players.length],
    ["Tutte le decklist valide", players.length > 0 && validDecks === players.length],
  ];
  els.checklist.innerHTML = checks
    .map(
      ([label, ok]) => `
        <div class="check-row">
          <span>${label}</span>
          <span class="badge ${ok ? "ok" : "warn"}">${ok ? "OK" : "Da fare"}</span>
        </div>
      `,
    )
    .join("");
}

function renderAttention(players) {
  const items = players
    .filter((player) => !player.paid || !player.deck?.valid)
    .map((player) => {
      const issues = [];
      if (!player.paid) issues.push("pagamento");
      if (!player.deck) issues.push("lista mancante");
      if (player.deck && !player.deck.valid) issues.push("lista non valida");
      return `
        <div class="attention-row">
          <span>${escapeHtml(player.name)}</span>
          <span class="badge bad">${issues.join(", ")}</span>
        </div>
      `;
    });
  els.attentionList.innerHTML = items.length
    ? items.join("")
    : '<p class="empty">Nessun blocco operativo per questo torneo.</p>';
}

function renderEvents() {
  els.eventsTable.innerHTML = state.events
    .map(
      (event) => `
        <tr>
          <td><strong>${escapeHtml(event.name)}</strong><br><small>${escapeHtml(event.rel)}</small></td>
          <td>${escapeHtml(event.format)}</td>
          <td>${formatDate(event.date)}</td>
          <td>${formatMoney(event.fee)}</td>
          <td>${activeCount(event.id)} / ${event.capacity}</td>
          <td>
            <div class="inline-actions">
              <button class="mini-button" data-action="select-event" data-id="${event.id}" type="button">Apri</button>
              <button class="mini-button" data-action="remove-event" data-id="${event.id}" type="button">Elimina</button>
            </div>
          </td>
        </tr>
      `,
    )
    .join("");
}

function renderPlayers(players) {
  els.playersTable.innerHTML = players.length
    ? players
        .map(
          (player) => `
        <tr>
          <td><strong>${escapeHtml(player.name)}</strong><br><small>${escapeHtml(player.email)}</small></td>
          <td>${escapeHtml(player.wizards || "N/D")}</td>
          <td>${escapeHtml(player.archetype || "Non dichiarato")}</td>
          <td>${deckBadge(player)}</td>
          <td>${paymentBadge(player)}</td>
          <td>
            <div class="inline-actions">
              <button class="mini-button" data-action="open-payment" data-id="${player.id}" type="button">Cassa</button>
              <button class="mini-button" data-action="remove-player" data-id="${player.id}" type="button">Rimuovi</button>
            </div>
          </td>
        </tr>
      `,
        )
        .join("")
    : '<tr><td colspan="6" class="empty">Nessun iscritto per questo torneo.</td></tr>';

  els.deckPlayer.innerHTML = players
    .map((player) => `<option value="${player.id}">${escapeHtml(player.name)}</option>`)
    .join("");
}

function renderDecks(players) {
  els.deckTable.innerHTML = players.length
    ? players
        .map((player) => {
          const deck = player.deck;
          return `
          <tr>
            <td>${escapeHtml(player.name)}</td>
            <td>${escapeHtml(player.archetype || "Non dichiarato")}</td>
            <td>${deck?.mainCount ?? "-"}</td>
            <td>${deck?.sideCount ?? "-"}</td>
            <td>${deckBadge(player, true)}</td>
            <td>
              <button class="mini-button" data-action="view-deck" data-id="${player.id}" type="button" ${
                deck ? "" : "disabled"
              }>Apri</button>
            </td>
          </tr>
        `;
        })
        .join("")
    : '<tr><td colspan="6" class="empty">Registra un giocatore prima di caricare una lista.</td></tr>';
}

function renderPayments(event, players) {
  els.paymentCards.innerHTML = players.length
    ? players
        .map(
          (player) => `
        <article class="payment-card">
          <header>
            <div>
              <strong>${escapeHtml(player.name)}</strong><br>
              <small>${escapeHtml(player.email)}</small>
            </div>
            ${paymentBadge(player)}
          </header>
          <div>
            <span class="eyebrow">Importo</span>
            <h3>${formatMoney(event.fee)}</h3>
          </div>
          <small>${player.paymentRef ? `Rif. ${escapeHtml(player.paymentRef)}` : "Nessun riferimento"}</small>
          <button class="${player.paid ? "secondary" : "primary"}" data-action="open-payment" data-id="${player.id}" type="button">
            ${player.paid ? "Aggiorna pagamento" : "Incassa"}
          </button>
        </article>
      `,
        )
        .join("")
    : '<p class="empty">Nessun pagamento da gestire.</p>';
}

function renderRounds(event) {
  const rounds = state.rounds.filter((round) => round.eventId === event.id);
  els.roundsContainer.innerHTML = rounds.length
    ? rounds
        .map(
          (round) => `
        <article class="round-card">
          <div>
            <strong>Round ${round.number}</strong>
            <div>${round.pairings
              .map(
                (pairing, index) =>
                  `<p>Tavolo ${index + 1}: ${escapeHtml(pairing[0])} vs ${escapeHtml(pairing[1] || "BYE")}</p>`,
              )
              .join("")}</div>
          </div>
          <span class="badge ok">${round.pairings.length} tavoli</span>
        </article>
      `,
        )
        .join("")
    : '<p class="empty">Genera il primo round quando pagamenti e liste sono sotto controllo.</p>';
}

function createEvent(event) {
  event.preventDefault();
  const item = {
    id: crypto.randomUUID(),
    name: document.querySelector("#eventName").value.trim(),
    format: document.querySelector("#eventFormat").value,
    date: document.querySelector("#eventDate").value,
    capacity: Number(document.querySelector("#eventCapacity").value),
    fee: Number(document.querySelector("#eventFee").value),
    rel: document.querySelector("#eventRel").value,
    notes: document.querySelector("#eventNotes").value.trim(),
  };
  state.events.push(item);
  state.activeEventId = item.id;
  event.target.reset();
  document.querySelector("#eventDate").value = today;
  toast("Torneo creato.");
  render();
}

function createPlayer(event) {
  event.preventDefault();
  const tournament = activeEvent();
  const players = activePlayers();
  if (players.length >= tournament.capacity) {
    toast("Capienza raggiunta.");
    return;
  }
  const player = {
    id: crypto.randomUUID(),
    eventId: tournament.id,
    name: document.querySelector("#playerName").value.trim(),
    email: document.querySelector("#playerEmail").value.trim(),
    wizards: document.querySelector("#playerWizards").value.trim(),
    archetype: document.querySelector("#playerArchetype").value.trim(),
    paid: false,
    paymentMethod: "",
    paymentRef: "",
    deck: null,
  };
  state.players.push(player);
  event.target.reset();
  toast("Giocatore registrato.");
  render();
}

function saveDecklist(event) {
  event.preventDefault();
  const playerId = els.deckPlayer.value;
  const player = state.players.find((item) => item.id === playerId);
  if (!player) return;
  const text = els.deckText.value.trim();
  if (!text) {
    toast("Incolla o carica una lista prima di salvare.");
    return;
  }
  player.deck = parseDeck(text, activeEvent().format);
  els.deckText.value = "";
  els.deckFile.value = "";
  toast(player.deck.valid ? "Lista salvata e valida." : player.deck.errors.join(" "));
  render();
}

function readDeckFile(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    els.deckText.value = String(reader.result || "");
  };
  reader.readAsText(file);
}

function parseDeck(raw, format) {
  const lines = raw.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  let section = "main";
  let mainCount = 0;
  let sideCount = 0;
  const cards = [];

  lines.forEach((line) => {
    if (/^(sideboard|side|sb)\b/i.test(line)) {
      section = "side";
      return;
    }
    const match = line.match(/^(\d+)\s+(.+)$/);
    if (!match) return;
    const count = Number(match[1]);
    const name = match[2].replace(/\s+\(.+\)$/, "").trim();
    cards.push({ count, name, section });
    if (section === "side") sideCount += count;
    else mainCount += count;
  });

  const errors = [];
  if (format === "Commander") {
    if (mainCount + sideCount !== 100) errors.push("Commander richiede esattamente 100 carte.");
  } else if (!["Draft", "Sealed"].includes(format) && mainCount < 60) {
    errors.push("Main deck sotto le 60 carte.");
  }
  if (sideCount > 15) errors.push("Sideboard oltre 15 carte.");
  if (!cards.length) errors.push("Formato lista non riconosciuto.");

  return {
    raw,
    cards,
    mainCount,
    sideCount,
    valid: errors.length === 0,
    errors,
    submittedAt: new Date().toISOString(),
  };
}

function generateRound() {
  const event = activeEvent();
  const eligible = activePlayers().filter((player) => player.paid && player.deck?.valid);
  if (eligible.length < 2) {
    toast("Servono almeno due giocatori pagati con lista valida.");
    return;
  }
  const shuffled = eligible
    .map((player) => ({ player, sort: Math.random() }))
    .sort((a, b) => a.sort - b.sort)
    .map(({ player }) => player.name);
  const pairings = [];
  for (let index = 0; index < shuffled.length; index += 2) {
    pairings.push([shuffled[index], shuffled[index + 1] || "BYE"]);
  }
  const number = state.rounds.filter((round) => round.eventId === event.id).length + 1;
  state.rounds.push({ id: crypto.randomUUID(), eventId: event.id, number, pairings });
  toast(`Round ${number} generato.`);
  render();
}

function markAllPaid() {
  activePlayers().forEach((player) => {
    player.paid = true;
    player.paymentMethod ||= "Organizer";
    player.paymentRef ||= "bulk-confirm";
  });
  toast("Pagamenti aggiornati.");
  render();
}

function openPayment(playerId) {
  const player = state.players.find((item) => item.id === playerId);
  if (!player) return;
  pendingPaymentPlayerId = playerId;
  els.paymentTitle.textContent = player.name;
  els.paymentSummary.textContent = `Entry fee ${formatMoney(activeEvent().fee)} per ${activeEvent().name}.`;
  els.paymentMethod.value = player.paymentMethod || "Carta";
  els.paymentRef.value = player.paymentRef || "";
  els.paymentDialog.showModal();
}

function confirmPayment() {
  const player = state.players.find((item) => item.id === pendingPaymentPlayerId);
  if (!player) return;
  player.paid = true;
  player.paymentMethod = els.paymentMethod.value;
  player.paymentRef = els.paymentRef.value.trim() || `${els.paymentMethod.value}-${Date.now()}`;
  els.paymentDialog.close();
  pendingPaymentPlayerId = null;
  toast("Pagamento confermato.");
  render();
}

function togglePaid(playerId) {
  const player = state.players.find((item) => item.id === playerId);
  if (!player) return;
  player.paid = !player.paid;
  render();
}

function removePlayer(playerId) {
  state.players = state.players.filter((player) => player.id !== playerId);
  toast("Giocatore rimosso.");
  render();
}

function removeEvent(eventId) {
  if (state.events.length === 1) {
    toast("Serve almeno un torneo.");
    return;
  }
  state.events = state.events.filter((event) => event.id !== eventId);
  state.players = state.players.filter((player) => player.eventId !== eventId);
  state.rounds = state.rounds.filter((round) => round.eventId !== eventId);
  state.activeEventId = state.events[0].id;
  toast("Torneo eliminato.");
  render();
}

function selectEvent(eventId) {
  state.activeEventId = eventId;
  showView("overview");
  render();
}

function viewDeck(playerId) {
  const player = state.players.find((item) => item.id === playerId);
  if (!player?.deck) return;
  const win = window.open("", "_blank");
  win.document.write(`<pre>${escapeHtml(player.deck.raw)}</pre>`);
  win.document.title = `Decklist - ${player.name}`;
  win.document.close();
}

function exportCsv() {
  const rows = [
    ["name", "email", "wizards", "archetype", "paid", "deck_valid", "main", "side"],
    ...activePlayers().map((player) => [
      player.name,
      player.email,
      player.wizards,
      player.archetype,
      player.paid ? "yes" : "no",
      player.deck?.valid ? "yes" : "no",
      player.deck?.mainCount || "",
      player.deck?.sideCount || "",
    ]),
  ];
  const csv = rows
    .map((row) => row.map((cell) => `"${String(cell).replaceAll('"', '""')}"`).join(","))
    .join("\n");
  download(`iscritti-${activeEvent().name}.csv`, csv, "text/csv");
}

function printDecks() {
  const content = activePlayers()
    .filter((player) => player.deck)
    .map((player) => `# ${player.name} - ${player.archetype || "N/D"}\n${player.deck.raw}`)
    .join("\n\n---\n\n");
  if (!content) {
    toast("Nessuna lista da stampare.");
    return;
  }
  const win = window.open("", "_blank");
  win.document.write(`<pre>${escapeHtml(content)}</pre>`);
  win.print();
}

function download(filename, content, type) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename.replace(/[^\w.-]+/g, "-").toLowerCase();
  link.click();
  URL.revokeObjectURL(url);
}

function resetDemo() {
  state = structuredClone(seedState);
  saveState();
  toast("Demo ripristinata.");
  render();
}

function showView(view) {
  els.navTabs.forEach((tab) => tab.classList.toggle("active", tab.dataset.view === view));
  document.querySelectorAll(".view").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.viewPanel === view);
  });
  if (view === "overview") {
    document.querySelector(".hero").scrollIntoView({ behavior: "smooth", block: "start" });
  } else {
    document.querySelector(".workspace").scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function deckBadge(player, verbose = false) {
  if (!player.deck) return '<span class="badge warn">Mancante</span>';
  if (player.deck.valid) return '<span class="badge ok">Valida</span>';
  return `<span class="badge bad">${verbose ? escapeHtml(player.deck.errors.join(" ")) : "Non valida"}</span>`;
}

function paymentBadge(player) {
  return player.paid
    ? '<span class="badge ok">Pagato</span>'
    : '<span class="badge warn">Da pagare</span>';
}

function activeCount(eventId) {
  return state.players.filter((player) => player.eventId === eventId).length;
}

function percent(value, total) {
  if (!total) return "0%";
  return `${Math.round((value / total) * 100)}%`;
}

function formatMoney(value) {
  return new Intl.NumberFormat("it-IT", { style: "currency", currency: "EUR" }).format(
    Number(value || 0),
  );
}

function formatDate(value) {
  return new Intl.DateTimeFormat("it-IT", { dateStyle: "medium" }).format(new Date(value));
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
  els.toast.textContent = message;
  els.toast.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => els.toast.classList.remove("show"), 2400);
}

function sampleDeck(spells, lands, side, valid) {
  const main = [
    `${Math.min(spells, 4)} Lightning Bolt`,
    `${Math.max(spells - 4, 0)} Expressive Iteration`,
    `${lands} Steam Vents`,
  ].join("\n");
  const sideboard = valid ? `\n\nSideboard\n${side} Mystical Dispute` : "";
  return parseDeck(`${main}${sideboard}`, "Modern");
}

document.querySelector("#eventDate").value = today;
