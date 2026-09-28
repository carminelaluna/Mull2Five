/**
 * formats.test.js — La tendina dei formati.
 *
 * Prima era un <input list="...">: la lista c'era, ma il browser la mostra solo
 * a chi comincia a scrivere, quindi il formato di fatto si digitava a mano.
 */
import { beforeEach, describe, expect, it } from 'vitest';

import { bindFormatPicker, formatOptions, formatPicker, formatValue } from '../js/formats.js';

const FORMATI = ['Modern', 'Pioneer', 'Commander'];

function monta(formats, current) {
  document.body.innerHTML = `<label>Formato${formatPicker('f', formats, current)}</label>`;
  bindFormatPicker('f');
  return { select: document.querySelector('#f'), altro: document.querySelector('#fAltro') };
}

describe('la scelta del formato', () => {
  beforeEach(() => { document.body.innerHTML = ''; });

  it('propone i formati del gioco in una tendina', () => {
    const { select } = monta(FORMATI, 'Modern');
    expect(select.tagName).toBe('SELECT');
    expect([...select.options].map((o) => o.value)).toEqual([...FORMATI, '__altro']);
    expect(select.value).toBe('Modern');
    expect(formatValue('f')).toBe('Modern');
  });

  it('tiene nascosto il campo libero finché non serve', () => {
    const { select, altro } = monta(FORMATI, 'Pioneer');
    expect(altro.style.display).toBe('none');
    select.value = '__altro';
    select.dispatchEvent(new Event('change'));
    expect(altro.style.display).toBe('');
  });

  it('restituisce quello scritto a mano quando si sceglie Altro', () => {
    const { select, altro } = monta(FORMATI, 'Modern');
    select.value = '__altro';
    select.dispatchEvent(new Event('change'));
    altro.value = '  Cubo del giovedì  ';
    expect(formatValue('f')).toBe('Cubo del giovedì');
  });

  it('riapre su Altro un formato che non è in elenco', () => {
    const { select, altro } = monta(FORMATI, 'Cubo del giovedì');
    expect(select.value).toBe('__altro');
    expect(altro.style.display).toBe('');
    expect(formatValue('f')).toBe('Cubo del giovedì');
  });

  it('cambiando gioco ripopola la tendina tenendo la scelta a mano', () => {
    const { select } = monta(FORMATI, 'Cubo del giovedì');
    select.innerHTML = formatOptions(['Standard', 'Draft'], formatValue('f'));
    expect(select.value).toBe('__altro');
  });
});
