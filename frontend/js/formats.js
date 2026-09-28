/**
 * formats.js — La scelta del formato di un torneo.
 *
 * Una tendina con i formati del gioco, e in fondo "Altro" per quelli di casa
 * (un Commander a squadre, un draft di cubo) che nessun elenco prevede. La usano
 * la creazione dell'evento e le sue impostazioni.
 */
import { esc } from './escape.js';
import { t as tr } from './i18n.js';

export const ALTRO = '__altro';

export function formatPicker(id, formats, current = '') {
  const libero = current && !formats.includes(current);
  return `<select id="${id}">${formatOptions(formats, current)}</select>
    <input id="${id}Altro" maxlength="60" placeholder="${esc(tr('Nome del formato'))}"
      value="${libero ? esc(current) : ''}" style="display:${libero ? '' : 'none'};margin-top:6px" />`;
}

export function formatOptions(formats, current = '') {
  const libero = current && !formats.includes(current);
  return formats.map((f) => `<option${f === current ? ' selected' : ''}>${esc(f)}</option>`).join('')
    + `<option value="${ALTRO}"${libero ? ' selected' : ''}>${esc(tr('Altro…'))}</option>`;
}

export function bindFormatPicker(id) {
  const select = document.querySelector(`#${id}`);
  const altro = document.querySelector(`#${id}Altro`);
  select.addEventListener('change', () => {
    altro.style.display = select.value === ALTRO ? '' : 'none';
    if (select.value === ALTRO) altro.focus();
  });
}

/** Il formato scelto: quello della tendina, o quello scritto a mano. */
export function formatValue(id) {
  const select = document.querySelector(`#${id}`);
  return select.value === ALTRO ? document.querySelector(`#${id}Altro`).value.trim() : select.value;
}
