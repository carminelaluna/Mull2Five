/**
 * organizer-common.js — I pezzi che tutte le sezioni del back-office usano.
 *
 * Stanno qui perche il back-office e diviso in piu file (organizer.js e
 * organizer-store.js) e questi servono a tutti: la sessione, la chiamata
 * all'API che porta al login se scade, e tre formattatori.
 */
import { apiRequest, requireSession } from './session.js';

// Pagina riservata: senza sessione valida si va al login, e poi si torna qui.
export const session = requireSession();

export const apiFetch = (path, opts = {}) => apiRequest(path, { requireLogin: true, ...opts });

export const $ = (s) => document.querySelector(s);
export const money = (c, cur = 'EUR') => ((c || 0) / 100).toLocaleString('it-IT', { style: 'currency', currency: cur });
export const fmtDate = (d) => d ? d.substring(0, 10).split('-').reverse().join('/') : '—';
