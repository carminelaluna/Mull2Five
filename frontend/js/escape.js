/**
 * escape.js — Testo dentro l'HTML, in un posto solo.
 *
 * Converte anche le virgolette. Il testo degli utenti finisce spesso dentro
 * attributi "..." (data-name, value, title): con le copie di esc che lasciavano
 * passare `"`, un nome come  x" onmouseover="…  chiudeva l'attributo e ne apriva
 * un altro, e quel codice girava nel browser di chi guardava — l'avversario, il
 * judge, l'organizzatore — con il suo token di sessione a portata di mano.
 *
 * Solo per l'HTML. Dove il testo va in textContent, confirm() o alert() si passa
 * così com'è: lì le entità si vedrebbero scritte.
 */
const ENTITIES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ENTITIES[c]);
