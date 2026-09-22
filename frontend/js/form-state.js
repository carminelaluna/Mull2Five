/**
 * form-state.js — Gli stati di un modulo: il pulsante che lavora e l'errore
 * accanto al campo sbagliato, invece di un messaggio generico in fondo.
 *
 * Gli stili sono in app.css: [aria-busy] mostra la rotellina, [aria-invalid]
 * colora il bordo del campo e .field-msg è il messaggio sotto di lui.
 */

/** Il pulsante mentre la richiesta è in corso: disattivato, con la rotellina e il testo dato. */
export function busy(button, on, label) {
  if (!button) return;
  if (on) {
    button.dataset.idleLabel ??= button.textContent;
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    if (label) button.textContent = label;
  } else {
    button.disabled = false;
    button.removeAttribute('aria-busy');
    if (button.dataset.idleLabel) button.textContent = button.dataset.idleLabel;
    delete button.dataset.idleLabel;
  }
}

/** Segna il campo come sbagliato, con il messaggio subito sotto; lo mette a fuoco. */
export function fieldError(input, message) {
  if (!input) return;
  input.setAttribute('aria-invalid', 'true');
  const host = input.closest('label') || input.parentElement;
  let msg = host.querySelector('.field-msg');
  if (!msg) {
    msg = document.createElement('span');
    msg.className = 'field-msg';
    msg.id = `${input.id || 'field'}-msg`;
    host.append(msg);
  }
  msg.textContent = message;
  input.setAttribute('aria-describedby', msg.id);
  input.focus();
  // Appena lo si corregge, l'errore sparisce.
  input.addEventListener(input.type === 'checkbox' ? 'change' : 'input', () => clearField(input), { once: true });
}

export function clearField(input) {
  input.removeAttribute('aria-invalid');
  input.removeAttribute('aria-describedby');
  (input.closest('label') || input.parentElement)?.querySelector('.field-msg')?.remove();
}

export function clearErrors(form) {
  form.querySelectorAll('[aria-invalid="true"]').forEach(clearField);
}
