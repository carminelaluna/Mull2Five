import { onReady } from './lang.js';   // prima di tutto: la lingua (vedi lang.js)
import { busy, clearErrors, fieldError } from './form-state.js';
import { t } from './i18n.js';
import {
  apiRequest,
  completeGoogleSignup,
  finishGoogleLogin,
  getSession,
  googleErrorText,
  safeNext,
  setToken,
  startGoogleLogin,
} from './session.js';

const params = new URLSearchParams(location.search);
// `next` arriva dall'indirizzo: solo pagine di questo sito.
const NEXT = safeNext(params.get('next'));
const REDIRECT = NEXT || 'my-registrations.html';
const fromGoogle = params.has('google') || params.has('google_error');

/* Dopo l'accesso: la pagina chiesta; senza, gli organizzatori partono dal back-office. */
function goOn(role = getSession()?.role) {
  location.replace(NEXT ? REDIRECT : (role === 'organizer' || role === 'admin' ? 'organizer.html' : REDIRECT));
}

/* Se già autenticato, vai alla pagina di destinazione */
if (getSession() && !fromGoogle) location.replace(REDIRECT);

onReady(() => {
  const tabLogin    = document.querySelector('#tabLogin');
  const tabRegister = document.querySelector('#tabRegister');
  const formLogin   = document.querySelector('#formLogin');
  const formReg     = document.querySelector('#formRegister');
  const formGoogle  = document.querySelector('#formGoogle');
  const googleBox   = document.querySelector('#googleBox');
  const googleBtn   = document.querySelector('#googleBtn');
  const googleLabel = document.querySelector('#googleLabel');

  tabLogin.addEventListener('click', () => {
    tabLogin.classList.add('active'); tabRegister.classList.remove('active');
    formLogin.classList.remove('hidden'); formReg.classList.add('hidden');
    document.querySelector('#errLogin').textContent = '';
    googleLabel.textContent = t('Accedi con Google');
  });
  tabRegister.addEventListener('click', () => {
    tabRegister.classList.add('active'); tabLogin.classList.remove('active');
    formReg.classList.remove('hidden'); formLogin.classList.add('hidden');
    document.querySelector('#errRegister').textContent = '';
    googleLabel.textContent = t('Registrati con Google');
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
      const { access_token } = await apiRequest('/auth/login', {
        method: 'POST',
        body: JSON.stringify({ email, password }),
      });
      setToken(access_token);
      goOn();
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
    if (!checkAgeAndTerms('#regAge', '#regTerms')) return;

    busy(btn, true, 'Registrazione in corso…');
    try {
      const { access_token } = await apiRequest('/auth/register', {
        method: 'POST',
        body: JSON.stringify({ display_name: name, email, password, role, age_confirmed: true, terms_accepted: true }),
      });
      setToken(access_token);
      // Un organizzatore parte dal back-office; un giocatore dalle sue iscrizioni.
      goOn(role);
    } catch (err) {
      if (err.status === 409) fieldError(document.querySelector('#regEmail'), 'Questa email ha già un account: accedi.');
      else errEl.textContent = err.message;
      busy(btn, false);
    }
  });

  /* ── Con Google ───────────────────────────────────────────────────── */

  googleBtn.addEventListener('click', async () => {
    // Non busy(): rimetterebbe il testo del bottone e toglierebbe il logo.
    googleBtn.disabled = true;
    googleBtn.setAttribute('aria-busy', 'true');
    try {
      await startGoogleLogin(NEXT);
    } catch (err) {
      const errEl = formLogin.classList.contains('hidden') ? '#errRegister' : '#errLogin';
      document.querySelector(errEl).textContent = err.message;
      googleBtn.disabled = false;
      googleBtn.removeAttribute('aria-busy');
    }
  });

  formGoogle.addEventListener('submit', async e => {
    e.preventDefault();
    const btn   = formGoogle.querySelector('button[type="submit"]');
    const errEl = document.querySelector('#errGoogle');
    const name  = document.querySelector('#googleName').value.trim();
    const role  = document.querySelector('#googleRole').value === 'organizer' ? 'organizer' : 'player';
    errEl.textContent = '';
    clearErrors(formGoogle);
    if (!checkAgeAndTerms('#googleAge', '#googleTerms')) return;

    busy(btn, true, 'Registrazione in corso…');
    try {
      await completeGoogleSignup({ display_name: name, role, age_confirmed: true, terms_accepted: true });
      goOn(role);
    } catch (err) {
      errEl.textContent = err.message;
      busy(btn, false);
    }
  });

  /* Di ritorno da Google: si entra, o si completa la registrazione. */
  if (fromGoogle) {
    // L'indirizzo torna pulito: un ricaricamento non rifà il giro.
    history.replaceState(null, '', location.pathname + (NEXT ? `?next=${encodeURIComponent(NEXT)}` : ''));
    const code = params.get('google_error');
    if (code) document.querySelector('#errLogin').textContent = googleErrorText(code);
    else returnFromGoogle();
  }

  async function returnFromGoogle() {
    try {
      const result = await finishGoogleLogin();
      if (result.access_token) { goOn(); return; }
      document.querySelector('.auth-tabs').classList.add('hidden');
      formLogin.classList.add('hidden');
      formReg.classList.add('hidden');
      googleBox.classList.add('hidden');
      formGoogle.classList.remove('hidden');
      document.querySelector('#googleEmail').textContent = result.signup_email || '';
      document.querySelector('#googleName').value = result.signup_name || '';
    } catch (err) {
      document.querySelector('#errLogin').textContent = err.message;
    }
  }
});

/* Età minima e termini, come nella registrazione con la password. */
function checkAgeAndTerms(ageSelector, termsSelector) {
  if (!document.querySelector(ageSelector).checked) {
    fieldError(document.querySelector(ageSelector),
      `Per aprire un account servono almeno ${document.querySelector('.age-years').textContent} anni: `
      + 'un genitore può aggiungerti come profilo dal suo account.');
    return false;
  }
  if (!document.querySelector(termsSelector).checked) {
    fieldError(document.querySelector(termsSelector), "Per aprire un account accetta i termini e l'informativa privacy.");
    return false;
  }
  return true;
}

// L'età minima la decide il server (MIN_ACCOUNT_AGE), e il bottone Google c'è
// solo se il server ha le credenziali.
fetch('/api/auth/rules').then((r) => r.json()).then((rules) => {
  if (rules.min_account_age) {
    document.querySelectorAll('.age-years').forEach((el) => { el.textContent = rules.min_account_age; });
  }
  const signingUp = !document.querySelector('#formGoogle')?.classList.contains('hidden');
  if (rules.google_login && !signingUp) document.querySelector('#googleBox')?.classList.remove('hidden');
}).catch(() => {});
