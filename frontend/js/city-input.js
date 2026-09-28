/**
 * city-input.js — Il campo "Città" che si completa da solo.
 *
 * Le città si scrivevano a mano e finivano scritte in tre modi ("Roma", "roma",
 * "ROMA"), quindi la ricerca per città non trovava niente. Qui si propongono
 * quelle che il sito conosce già (/api/cities): chi apre il secondo negozio a
 * Roma sceglie la stessa parola di chi c'era prima. Resta un campo libero, per
 * la prima volta che si gioca in un posto nuovo.
 */
import { esc } from './escape.js';

/** Attacca il completamento a un <input>. Torna una funzione per staccarlo. */
export function cityInput(input) {
  if (!input || input.dataset.cityBound) return () => {};
  input.dataset.cityBound = '1';
  input.setAttribute('autocomplete', 'off');

  const box = document.createElement('ul');
  box.className = 'card-suggest';
  box.hidden = true;
  input.insertAdjacentElement('afterend', box);
  if (getComputedStyle(input.parentElement).position === 'static') {
    input.parentElement.style.position = 'relative';
  }

  let timer = null;
  let attiva = -1;

  const close = () => { box.hidden = true; box.innerHTML = ''; attiva = -1; };
  const voci = () => [...box.querySelectorAll('li')];
  const evidenzia = (i) => {
    const lista = voci();
    attiva = lista.length ? (i + lista.length) % lista.length : -1;
    lista.forEach((li, n) => li.classList.toggle('active', n === attiva));
  };
  const scegli = (citta) => {
    input.value = citta;
    close();
    input.dispatchEvent(new Event('change', { bubbles: true }));
  };

  const cerca = async () => {
    const q = input.value.trim();
    if (q.length < 2) { close(); return; }
    let trovate = [];
    try {
      const r = await fetch(`/api/cities?q=${encodeURIComponent(q)}`);
      trovate = r.ok ? await r.json() : [];
    } catch { return; }          // offline: resta un campo libero
    // Se l'unica proposta è già quello che si è scritto, non serve dirlo.
    if (!trovate.length || (trovate.length === 1 && trovate[0].toLowerCase() === q.toLowerCase())) {
      close();
      return;
    }
    box.innerHTML = trovate.map((c) => `<li>${esc(c)}</li>`).join('');
    box.hidden = false;
    attiva = -1;
  };

  input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(cerca, 200); });
  input.addEventListener('keydown', (e) => {
    if (box.hidden) return;
    if (e.key === 'ArrowDown') { e.preventDefault(); evidenzia(attiva + 1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); evidenzia(attiva - 1); }
    else if (e.key === 'Enter' && attiva >= 0) { e.preventDefault(); scegli(voci()[attiva].textContent); }
    else if (e.key === 'Escape') close();
  });
  // mousedown e non click: il blur arriva prima del click e chiuderebbe la lista.
  box.addEventListener('mousedown', (e) => {
    const li = e.target.closest('li');
    if (li) { e.preventDefault(); scegli(li.textContent); }
  });
  input.addEventListener('blur', () => setTimeout(close, 120));

  return () => { clearTimeout(timer); close(); box.remove(); delete input.dataset.cityBound; };
}
