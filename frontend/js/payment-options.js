/**
 * payment-options.js — Se su questo sito si paga anche online o solo al banco.
 *
 * Con i pagamenti online spenti (ONLINE_PAYMENTS_ENABLED, GET /api/payments/options)
 * le caselle Stripe e PayPal del back-office spariscono (app.css, `.pay-online`):
 * il server non le salverebbe comunque, e una casella che non fa niente confonde.
 */
import { apiRequest } from './session.js';

if (typeof document !== 'undefined') {
  apiRequest('/payments/options')
    .then((options) => {
      if (options?.online === false) document.documentElement.dataset.onlinePayments = 'off';
    })
    .catch(() => {});   // senza risposta restano visibili: decide comunque il server
}
