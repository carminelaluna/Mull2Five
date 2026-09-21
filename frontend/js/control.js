/**
 * control.js — Regia a tutto schermo.
 *
 * La console vera sta in console.js: qui restano solo il guardiano della
 * sessione e la scelta del torneo. Questa pagina serve in sala — su un secondo
 * schermo e ai judge, che nel back-office non entrano — mentre l'organizzatore
 * trova la stessa console dentro la pagina dell'evento.
 */
import { mountConsole } from './console.js';
import { esc } from './escape.js';

const TOKEN_KEY = 'mull2five-jwt-v1';
const token = localStorage.getItem(TOKEN_KEY);
if (!token) location.replace('login.html?next=control.html');

function decodeJwt(t) {
  try { return JSON.parse(atob(t.split('.')[1].replace(/-/g, '+').replace(/_/g, '/'))); }
  catch { return null; }
}
const session = decodeJwt(token);
if (!session || session.exp < Date.now() / 1000) {
  localStorage.removeItem(TOKEN_KEY);
  location.replace('login.html?next=control.html');
}

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
  $('#logoutBtn').addEventListener('click', () => {
    localStorage.removeItem(TOKEN_KEY);
    location.replace('index.html');
  });

  let mine = [];
  try {
    const r = await fetch('/api/tournaments/mine', { headers: { Authorization: `Bearer ${token}` } });
    mine = r.ok ? await r.json() : [];
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

document.addEventListener('DOMContentLoaded', init);
