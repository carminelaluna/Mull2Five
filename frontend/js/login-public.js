import { onReady } from './lang.js';   // prima di tutto: la lingua (vedi lang.js)
import { busy, clearErrors, fieldError } from './form-state.js';
const API       = '/api';
const TOKEN_KEY = 'mull2five-jwt-v1';
const REDIRECT  = new URLSearchParams(location.search).get('next') || 'my-registrations.html';

/* Il messaggio d'errore del server: una frase, o la lista di FastAPI per i campi non validi. */
function detailText(err, fallback) {
  if (Array.isArray(err.detail)) return err.detail.map((d) => d.msg).join(' · ') || fallback;
  return err.detail || fallback;
}

function decodeJwt(t) {
  try { return JSON.parse(atob(t.split('.')[1].replace(/-/g,'+').replace(/_/g,'/'))); }
  catch { return null; }
}

/* Se già autenticato, vai alla pagina di destinazione */
const existing = localStorage.getItem(TOKEN_KEY);
if (existing) {
  const p = decodeJwt(existing);
  if (p && p.exp > Date.now() / 1000) location.replace(REDIRECT);
}

onReady(() => {
  const tabLogin    = document.querySelector('#tabLogin');
  const tabRegister = document.querySelector('#tabRegister');
  const formLogin   = document.querySelector('#formLogin');
  const formReg     = document.querySelector('#formRegister');

  tabLogin.addEventListener('click', () => {
    tabLogin.classList.add('active'); tabRegister.classList.remove('active');
    formLogin.classList.remove('hidden'); formReg.classList.add('hidden');
    document.querySelector('#errLogin').textContent = '';
  });
  tabRegister.addEventListener('click', () => {
    tabRegister.classList.add('active'); tabLogin.classList.remove('active');
    formReg.classList.remove('hidden'); formLogin.classList.add('hidden');
    document.querySelector('#errRegister').textContent = '';
  });

  formLogin.addEventListener('submit', async e => {
    e.preventDefault();
    const btn = formLogin.querySelector('button');
    const email    = document.querySelector('#loginEmail').value.trim();
    const password = document.querySelector('#loginPassword').value;
    const errEl    = document.querySelector('#errLogin');
    busy(btn, true, 'Accesso in corso…');
    errEl.textContent = '';
    try {
      const res = await fetch(API + '/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(detailText(err, 'Credenziali non valide.'));
      }
      const { access_token } = await res.json();
      localStorage.setItem(TOKEN_KEY, access_token);
      // Senza ?next esplicito, gli organizzatori partono dal back-office.
      const hasNext = new URLSearchParams(location.search).get('next');
      const role = decodeJwt(access_token)?.role;
      location.replace(hasNext ? REDIRECT : (role === 'organizer' || role === 'admin' ? 'organizer.html' : REDIRECT));
    } catch (err) {
      errEl.textContent = err.message;
      busy(btn, false);
    }
  });

  formReg.addEventListener('submit', async e => {
    e.preventDefault();
    const btn     = formReg.querySelector('button');
    const errEl   = document.querySelector('#errRegister');
    const name     = document.querySelector('#regName').value.trim();
    const email    = document.querySelector('#regEmail').value.trim();
    const password = document.querySelector('#regPassword').value;
    const confirm  = document.querySelector('#regConfirm').value;
    const role     = document.querySelector('#regRole')?.value === 'organizer' ? 'organizer' : 'player';
    errEl.textContent = '';
    clearErrors(formReg);

    // Ogni errore accanto al suo campo: si vede subito cosa correggere.
    if (password.length < 8) { fieldError(document.querySelector('#regPassword'), 'Minimo 8 caratteri.'); return; }
    if (password !== confirm) { fieldError(document.querySelector('#regConfirm'), 'Le password non coincidono.'); return; }
    if (!document.querySelector('#regAge').checked) {
      fieldError(document.querySelector('#regAge'),
        `Per aprire un account servono almeno ${document.querySelector('#regAgeYears').textContent} anni: `
        + 'un genitore può aggiungerti come profilo dal suo account.');
      return;
    }
    if (!document.querySelector('#regTerms').checked) {
      fieldError(document.querySelector('#regTerms'), "Per aprire un account accetta i termini e l'informativa privacy.");
      return;
    }

    busy(btn, true, 'Registrazione in corso…');
    try {
      const res = await fetch(API + '/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ display_name: name, email, password, role, age_confirmed: true, terms_accepted: true }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        // Email già usata: l'errore va sul campo dell'email.
        if (res.status === 409) { fieldError(document.querySelector('#regEmail'), 'Questa email ha già un account: accedi.'); busy(btn, false); return; }
        throw new Error(detailText(err, 'Errore durante la registrazione.'));
      }
      const { access_token } = await res.json();
      localStorage.setItem(TOKEN_KEY, access_token);
      // Un organizzatore parte dal back-office; un giocatore dalle sue iscrizioni.
      const hasNext = new URLSearchParams(location.search).get('next');
      location.replace(hasNext ? REDIRECT : (role === 'organizer' ? 'organizer.html' : REDIRECT));
    } catch (err) {
      errEl.textContent = err.message;
      busy(btn, false);
    }
  });
});

// L'età minima la decide il server (MIN_ACCOUNT_AGE).
fetch(API + '/auth/rules').then((r) => r.json()).then((rules) => {
  const years = document.querySelector('#regAgeYears');
  if (years && rules.min_account_age) years.textContent = rules.min_account_age;
}).catch(() => {});
