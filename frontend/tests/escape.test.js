/**
 * escape.test.js — Il testo degli utenti non deve poter uscire da un attributo.
 *
 * Nomi, archetipi e nomi di torneo li scrive un utente e li legge un altro:
 * se una virgoletta chiude l'attributo, quello che segue diventa codice nel
 * browser di chi guarda.
 */
import { describe, it, expect } from 'vitest';
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { esc } from '../js/escape.js';
import { eventTile } from '../js/catalog.js';

const PAYLOAD = 'x" onmouseover="alert(1)';
const PAYLOAD_APICE = "x' onfocus='alert(1)";

/** I gestori on* presenti nel frammento: se ce n'è anche uno, il testo è uscito. */
function handlers(html) {
  const box = document.createElement('div');
  box.innerHTML = html;
  return [...box.querySelectorAll('*')].flatMap((el) =>
    [...el.attributes].filter((a) => a.name.startsWith('on')).map((a) => a.name));
}

describe('esc', () => {
  it('converte i cinque caratteri speciali', () => {
    expect(esc(`<a href="x">L'&</a>`))
      .toBe('&lt;a href=&quot;x&quot;&gt;L&#39;&amp;&lt;/a&gt;');
  });

  it('null e undefined diventano stringa vuota, i numeri testo', () => {
    expect(esc(null)).toBe('');
    expect(esc(undefined)).toBe('');
    expect(esc(42)).toBe('42');
  });

  it('un nome con le virgolette resta dentro il suo attributo', () => {
    const box = document.createElement('div');
    box.innerHTML = `<button data-name="${esc(PAYLOAD)}">${esc(PAYLOAD)}</button>`;
    const btn = box.querySelector('button');
    expect([...btn.attributes].map((a) => a.name)).toEqual(['data-name']);
    // Il browser decodifica: chi rilegge dataset o textContent ritrova il nome vero.
    expect(btn.dataset.name).toBe(PAYLOAD);
    expect(btn.textContent).toBe(PAYLOAD);
  });

  it('vale anche negli attributi tra apici singoli', () => {
    expect(handlers(`<input value='${esc(PAYLOAD_APICE)}'>`)).toEqual([]);
  });

  it('con la copia vecchia lo stesso nome aggiungeva un gestore', () => {
    // Prova che il controllo sa riconoscere il problema, non che passa a vuoto.
    const vecchio = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    expect(handlers(`<button data-name="${vecchio(PAYLOAD)}"></button>`)).toEqual(['onmouseover']);
  });
});

describe('template reali', () => {
  it('una scheda evento con tutti i campi ostili non produce gestori', () => {
    const html = eventTile({
      id: 1, name: PAYLOAD, event_type: PAYLOAD, format: PAYLOAD, venue: PAYLOAD,
      start_time: PAYLOAD, starts_on: '2026-10-01', capacity: 8, registered_players: 0,
    });
    expect(handlers(html)).toEqual([]);
  });
});

describe('una sola copia', () => {
  it('nessuna pagina definisce un esc suo', () => {
    // Le copie locali erano il problema: ognuna poteva dimenticare le virgolette.
    // Sotto jsdom import.meta.url non e un URL di file: si parte dalla cartella
    // da cui gira vitest, cioe frontend/, e lo si verifica.
    const root = process.cwd();
    expect(existsSync(join(root, 'js', 'escape.js'))).toBe(true);
    const files = [
      ...readdirSync(join(root, 'js')).filter((f) => f.endsWith('.js')).map((f) => `js/${f}`),
      ...readdirSync(root).filter((f) => f.endsWith('.html')),
    ];
    const copie = files.filter((f) => f !== 'js/escape.js'
      && /(?:const|let|function)\s+esc\s*[=(]/.test(readFileSync(join(root, f), 'utf8')));
    expect(copie).toEqual([]);
  });
});
