/**
 * facets-toggle.js — Sul telefono i filtri stanno chiusi dietro un pulsante.
 *
 * Nelle ricerche (eventi, liste) i filtri sono una colonna a sinistra. Sotto gli
 * 860 px la colonna va sopra i risultati, e aperta occupava due schermate: il
 * primo torneo compariva a 1661 px dall'alto (24/11/2026), e chi apre il sito
 * dal telefono — quasi tutti i giocatori — vedeva solo caselle da spuntare.
 * Ora si vede subito la frase che riassume i filtri e poi i risultati; i filtri
 * si aprono col pulsante. Sul computer il pulsante non c'è e non cambia niente.
 */
const button = document.querySelector('.facets-toggle');
const panel = button && document.getElementById(button.getAttribute('aria-controls'));

button?.addEventListener('click', () => {
  const open = button.getAttribute('aria-expanded') !== 'true';
  button.setAttribute('aria-expanded', String(open));
  panel?.classList.toggle('open', open);
});
