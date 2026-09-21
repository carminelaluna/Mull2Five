/**
 * i18n.test.js — Lingue dell'interfaccia.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { detectLanguage, getLang, ready, t, translatePage } from '../js/i18n.js';

beforeEach(async () => {
  localStorage.clear();
  await ready('it');
});

describe('t()', () => {
  it("in italiano restituisce il testo com'è", () => {
    expect(t('Lingua')).toBe('Lingua');
  });

  it('nelle altre lingue usa il dizionario', async () => {
    await ready('en');
    expect(getLang()).toBe('en');
    expect(t('Lingua')).toBe('Language');
  });

  it('una stringa non tradotta resta leggibile, in italiano', async () => {
    await ready('de');
    expect(t('Testo che nessuno ha tradotto')).toBe('Testo che nessuno ha tradotto');
  });

  it('sostituisce i segnaposto, anche nel testo di ripiego', () => {
    expect(t('Si gioca il {data} a {luogo}', { data: '12/10', luogo: 'Milano' }))
      .toBe('Si gioca il 12/10 a Milano');
    expect(t('Manca {x}', {})).toBe('Manca {x}');
  });
});

describe('scelta della lingua', () => {
  it('ricorda quella salvata', () => {
    localStorage.setItem('mull2five-lang', 'fr');
    expect(detectLanguage()).toBe('fr');
  });

  it('ignora un valore salvato che non è una lingua supportata', () => {
    localStorage.setItem('mull2five-lang', 'xx');
    expect(['it', 'en', 'es', 'fr', 'de']).toContain(detectLanguage());
  });

  it('una lingua sconosciuta ricade sull’italiano', async () => {
    await ready('xx');
    expect(getLang()).toBe('it');
  });
});

describe('translatePage()', () => {
  it('traduce testo e attributi segnati, e si può ripetere senza perdere l’originale', async () => {
    document.body.innerHTML = `
      <span data-i18n>Lingua</span>
      <input data-i18n-attr="placeholder" placeholder="Lingua">`;
    await ready('es');
    translatePage();
    translatePage();
    expect(document.querySelector('span').textContent).toBe('Idioma');
    expect(document.querySelector('input').placeholder).toBe('Idioma');
  });
});
