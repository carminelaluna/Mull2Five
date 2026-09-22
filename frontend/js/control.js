/**
 * control.js — Regia a tutto schermo.
 *
 * La console vera sta in console.js: qui restano solo il guardiano della
 * sessione e la scelta del torneo. Questa pagina serve in sala — su un secondo
 * schermo e ai judge, che nel back-office non entrano — mentre l'organizzatore
 * trova la stessa console dentro la pagina dell'evento.
 */
import { onReady } from './lang.js';   // prima di tutto: la lingua (vedi lang.js)
import { mountConsole } from './console.js';
import { esc } from './escape.js';
import { apiRequest, logout, requireSession } from './session.js';

const session = requireSession();

const $ = (s) => document.querySelector(s);

let _console = null;

function open(tid) {
  _console?.destroy();
  _console = mountConsole($('#consoleHost'), tid);
}

async function init() {
  $('#publicAuth').innerHTML =
    `<span style="color:var(--muted);font-size:.85rem">${esc(session.email)}</span>
     <button class="secondary-link" id="logoutBtn" type="button">Esci</button>`;
  $('#logoutBtn').addEventListener('click', () => logout('index.html'));

  let mine = [];
  try {
    mine = await apiRequest('/tournaments/mine', { requireLogin: true });
  } catch { mine = []; }

  const running = mine.filter((t) => ['running', 'published'].includes(t.status));
  const list = running.length ? running : mine;
  if (!list.length) {
    $('#consoleHost').innerHTML = '<p class="empty">Nessun torneo gestibile su questo account.</p>';
    return;
  }

  const select = $('#tournamentSelect');
  select.innerHTML = list.map((t) => `<option value="${t.id}">${esc(t.name)}</option>`).join('');
  const wanted = new URLSearchParams(location.search).get('t');
  const tid = wanted && list.some((t) => String(t.id) === wanted) ? wanted : String(list[0].id);
  select.value = tid;
  select.addEventListener('change', (e) => open(e.target.value));

  open(tid);
}

onReady(init);
