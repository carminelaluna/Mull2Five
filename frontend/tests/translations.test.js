/**
 * translations.test.js — Nessuna frase senza traduzione.
 *
 * Le chiavi del dizionario sono i testi italiani: se qualcuno cambia una frase
 * e dimentica i dizionari, nelle altre lingue ricompare l'italiano senza che
 * nessuno se ne accorga. Qui si legge il codice, si raccolgono le frasi passate
 * a t()/tr() e si controlla che ci siano in tutte le lingue.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const LANGUAGES = ['en', 'es', 'fr', 'de'];
// t('…') e tr('…'), anche con apostrofi escapati; i testi costruiti a pezzi non si vedono.
const CALL = /(?<![\w$.])(?:t|tr)\(\s*(['"])((?:\\.|(?!\1).)+?)\1/g;

function phrases() {
  const found = new Map();
  for (const name of fs.readdirSync(path.join(ROOT, 'js'))) {
    if (!name.endsWith('.js')) continue;
    const source = fs.readFileSync(path.join(ROOT, 'js', name), 'utf8');
    for (const match of source.matchAll(CALL)) {
      const text = match[2].replace(/\\'/g, "'").replace(/\\"/g, '"').replace(/\\\\/g, '\\');
      if (!found.has(text)) found.set(text, name);
    }
  }
  return found;
}

const dictionaries = Object.fromEntries(
  LANGUAGES.map((lang) => [lang, JSON.parse(fs.readFileSync(path.join(ROOT, 'locales', `${lang}.json`), 'utf8'))]),
);

describe('i dizionari', () => {
  it('hanno tutte le frasi che il codice traduce', () => {
    const missing = [];
    for (const [text, file] of phrases()) {
      for (const lang of LANGUAGES) {
        if (!(text in dictionaries[lang])) missing.push(`${lang}: "${text}" (${file})`);
      }
    }
    expect(missing).toEqual([]);
  });

  it('non hanno traduzioni vuote', () => {
    const empty = [];
    for (const lang of LANGUAGES) {
      for (const [key, value] of Object.entries(dictionaries[lang])) {
        if (!String(value).trim()) empty.push(`${lang}: "${key}"`);
      }
    }
    expect(empty).toEqual([]);
  });

  it('tengono i segnaposto della frase italiana', () => {
    const broken = [];
    const slots = (text) => (text.match(/\{[a-z_]+\}/g) || []).sort().join(',');
    for (const lang of LANGUAGES) {
      for (const [key, value] of Object.entries(dictionaries[lang])) {
        if (slots(key) !== slots(String(value))) broken.push(`${lang}: "${key}" → "${value}"`);
      }
    }
    expect(broken).toEqual([]);
  });
});
