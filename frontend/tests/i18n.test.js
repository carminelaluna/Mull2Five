import { describe, it, expect, beforeEach } from 'vitest';
import { initI18n, t, setLang, getLang } from '../js/i18n.js';

describe('i18n', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <header class="public-header"><div class="public-auth"></div></header>
      <a data-i18n="nav.tournaments">X</a>
      <input data-i18n-placeholder="search.name" />`;
    localStorage.clear();
  });

  it('default lingua italiana e traduce le chiavi note', () => {
    initI18n();
    expect(getLang()).toBe('it');
    expect(t('nav.tournaments')).toBe('Tornei');
  });

  it('applica le traduzioni agli elementi data-i18n', () => {
    initI18n();
    expect(document.querySelector('[data-i18n]').textContent).toBe('Tornei');
    expect(document.querySelector('[data-i18n-placeholder]').getAttribute('placeholder'))
      .toBe('Nome torneo…');
  });

  it('setLang(en) cambia lingua, persiste e ritraduce', () => {
    initI18n();
    setLang('en');
    expect(getLang()).toBe('en');
    expect(t('nav.tournaments')).toBe('Tournaments');
    expect(localStorage.getItem('arcana-lang')).toBe('en');
    expect(document.querySelector('[data-i18n]').textContent).toBe('Tournaments');
    expect(document.documentElement.lang).toBe('en');
  });

  it('chiave sconosciuta ritorna la chiave stessa', () => {
    initI18n();
    expect(t('non.existing.key')).toBe('non.existing.key');
  });

  it('monta il selettore lingua IT/EN una sola volta', () => {
    initI18n();
    initI18n();
    expect(document.querySelectorAll('#langSwitch').length).toBe(1);
    expect(document.querySelectorAll('#langSwitch button').length).toBe(2);
  });
});
