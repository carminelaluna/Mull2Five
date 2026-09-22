/**
 * eslint.config.js — La rete sotto il refactoring.
 *
 * Serve soprattutto per no-undef: in JavaScript un nome sbagliato dentro un
 * template literal non si vede finché qualcuno non apre quella pagina, e i
 * test non entrano in ogni ramo dell'HTML che generiamo.
 */
import js from '@eslint/js';
import globals from 'globals';

export default [
  { ignores: ['dist/**', 'node_modules/**', 'coverage/**', 'test-results/**', 'playwright-report/**'] },
  js.configs.recommended,
  {
    files: ['js/**/*.js'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: globals.browser,
    },
  },
  {
    // Il service worker gira fuori dalla pagina: self, caches, fetch sono suoi.
    files: ['public/sw.js'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'script',
      globals: globals.serviceworker,
    },
  },
  {
    files: ['*.config.js', 'tests/**/*.js', 'e2e/**/*.js'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: { ...globals.node, ...globals.browser },
    },
  },
  {
    rules: {
      // Inizializzare una variabile e poi riempirla dentro un try e voluto:
      // se la chiamata fallisce si va avanti con il valore di partenza.
      'no-useless-assignment': 'off',
    },
  },
];
