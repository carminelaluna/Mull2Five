const API       = '/api';
const TOKEN_KEY = 'arcana-events-jwt-v1';
const REDIRECT  = new URLSearchParams(location.search).get('next') || 'my-registrations.html';

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

document.addEventListener('DOMContentLoaded', () => {
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
    btn.disabled = true; btn.textContent = 'Accesso in corso…';
    errEl.textContent = '';
    try {
      const res = await fetch(API + '/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Credenziali non valide.');
      }
      const { access_token } = await res.json();
      localStorage.setItem(TOKEN_KEY, access_token);
      // Senza ?next esplicito, gli organizzatori partono dal back-office.
      const hasNext = new URLSearchParams(location.search).get('next');
      const role = decodeJwt(access_token)?.role;
      location.replace(hasNext ? REDIRECT : (role === 'organizer' || role === 'admin' ? 'organizer.html' : REDIRECT));
    } catch (err) {
      errEl.textContent = err.message;
    } finally {
      btn.disabled = false; btn.textContent = 'Accedi';
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

    if (password.length < 8) { errEl.textContent = 'Password: minimo 8 caratteri.'; return; }
    if (password !== confirm)  { errEl.textContent = 'Le password non coincidono.'; return; }

    btn.disabled = true; btn.textContent = 'Registrazione in corso…';
    try {
      const res = await fetch(API + '/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ display_name: name, email, password, role }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Errore durante la registrazione.');
      }
      const { access_token } = await res.json();
      localStorage.setItem(TOKEN_KEY, access_token);
      // Un organizzatore parte dal back-office; un giocatore dalle sue iscrizioni.
      const hasNext = new URLSearchParams(location.search).get('next');
      location.replace(hasNext ? REDIRECT : (role === 'organizer' ? 'organizer.html' : REDIRECT));
    } catch (err) {
      errEl.textContent = err.message;
    } finally {
      btn.disabled = false; btn.textContent = 'Crea account';
    }
  });
});
