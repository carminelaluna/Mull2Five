/**
 * coverage.js — Scheda riassuntiva di un torneo concluso, pronta da pubblicare.
 *
 * Vincitore, top 8 e metagame in un'immagine sola. L'articolo dei judge FAB
 * descrive il giro attuale: finito il torneo si va su uno strumento esterno, si
 * reinseriscono i nomi a mano e si esporta il png. Qui i dati ci sono già.
 *
 * Il disegno è su canvas con le API 2D, senza librerie: serve un png a misura
 * esatta per il social, e una conversione da HTML non la garantisce (font che
 * slittano, dipendenze esterne, immagini bloccate dal CORS).
 */
import { onReady } from './lang.js';   // prima di tutto: la lingua (vedi lang.js)
import { apiGet, esc, fmtDate, updateAuthNav } from './catalog.js';

const $ = (s) => document.querySelector(s);

/* Misure dei formati social più usati dai negozi. */
const SIZES = {
  square:  { w: 1080, h: 1080, label: 'Quadrato · Instagram' },
  wide:    { w: 1200, h: 675,  label: 'Orizzontale · X, Facebook' },
  story:   { w: 1080, h: 1920, label: 'Verticale · Storie' },
};

const INK = '#ffffff';
const MUTED = '#9a9aa5';
const ACCENT = '#c6ff3d';
const BG = '#0d0d0f';
const PANEL = '#16161a';

let _data = null;
let _size = 'square';

/* ── Disegno ───────────────────────────────────────────────── */

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, r);
}

/** Taglia il testo con l'ellissi se non sta nello spazio dato. */
function fitText(ctx, text, maxWidth) {
  let s = String(text ?? '');
  if (ctx.measureText(s).width <= maxWidth) return s;
  while (s.length > 1 && ctx.measureText(s + '…').width > maxWidth) s = s.slice(0, -1);
  return s + '…';
}

function drawCard(canvas, size) {
  const { w, h } = SIZES[size];
  const ctx = canvas.getContext('2d');
  canvas.width = w;
  canvas.height = h;

  const pad = Math.round(Math.min(w, h) * 0.065);
  const wide = w / h > 1.4;          // 16:9 non ha altezza per impilare tutto
  const narrow = w / h < 1;          // la storia ha altezza da vendere
  // La scala segue l'altezza disponibile: legandola alla larghezza, su una
  // scheda bassa intestazione e vincitore si mangiavano tutto e le liste
  // sparivano. Il 16:9 ha meno altezza ma una colonna sola da riempire, quindi
  // regge un rapporto piu generoso del quadrato.
  const scale = wide ? h / 760 : Math.min(w, h) / 1080;

  ctx.fillStyle = BG;
  ctx.fillRect(0, 0, w, h);

  // Alone del brand in alto a sinistra, come sul sito.
  const glow = ctx.createRadialGradient(0, 0, 0, 0, 0, w * 0.8);
  glow.addColorStop(0, 'rgba(198, 255, 61, 0.10)');
  glow.addColorStop(1, 'rgba(198, 255, 61, 0)');
  ctx.fillStyle = glow;
  ctx.fillRect(0, 0, w, h);

  // Su 16:9 la scheda si legge in due colonne: a sinistra chi ha vinto,
  // a destra i numeri. In verticale resta il flusso dall'alto in basso.
  const headW = wide ? (w - pad * 3) * 0.55 : w - pad * 2;
  // In orizzontale il blocco di sinistra si centra: lasciarlo in alto lasciava
  // meta scheda vuota.
  const headH = (52 + 64 + 62 + 132) * scale;
  let y = wide ? Math.max(pad, (h - headH) / 2) : pad;
  const headTop = y;   // le liste si allineano a questa riga, non al bordo

  // ── Intestazione ──
  ctx.fillStyle = ACCENT;
  ctx.font = `700 ${Math.round(22 * scale)}px Inter, system-ui, sans-serif`;
  ctx.fillText('MULL2FIVE', pad, y + 22 * scale);
  y += 52 * scale;

  ctx.fillStyle = INK;
  ctx.font = `800 ${Math.round((narrow ? 50 : wide ? 38 : 46) * scale)}px Inter, system-ui, sans-serif`;
  ctx.fillText(fitText(ctx, _data.name, headW), pad, y + 46 * scale);
  y += (narrow ? 78 : 64) * scale;

  ctx.fillStyle = MUTED;
  ctx.font = `500 ${Math.round(26 * scale)}px Inter, system-ui, sans-serif`;
  const sub = [_data.format, fmtDate(_data.starts_on), `${_data.players} giocatori`]
    .filter(Boolean).join('  ·  ');
  ctx.fillText(fitText(ctx, sub, headW), pad, y + 24 * scale);
  y += 62 * scale;

  // ── Vincitore ──
  const winner = _data.standings[0];
  if (winner) {
    const boxH = 132 * scale;
    ctx.fillStyle = 'rgba(198, 255, 61, 0.12)';
    roundRect(ctx, pad, y, headW, boxH, 18 * scale);
    ctx.fill();
    ctx.strokeStyle = ACCENT;
    ctx.lineWidth = 2 * scale;
    ctx.stroke();

    ctx.fillStyle = ACCENT;
    ctx.font = `700 ${Math.round(20 * scale)}px Inter, system-ui, sans-serif`;
    ctx.fillText('VINCITORE', pad + 28 * scale, y + 38 * scale);

    ctx.fillStyle = INK;
    ctx.font = `800 ${Math.round(40 * scale)}px Inter, system-ui, sans-serif`;
    ctx.fillText(fitText(ctx, winner.name, headW - 56 * scale), pad + 28 * scale, y + 84 * scale);

    if (winner.archetype) {
      ctx.fillStyle = MUTED;
      ctx.font = `500 ${Math.round(24 * scale)}px Inter, system-ui, sans-serif`;
      ctx.fillText(fitText(ctx, winner.archetype, headW - 56 * scale), pad + 28 * scale, y + 116 * scale);
    }
    y += boxH + 44 * scale;
  }

  // ── Top 8 e metagame ──
  const colGap = 32 * scale;
  const bottom = h - pad - 46 * scale;
  // In orizzontale le liste stanno a destra e partono dall'alto, accanto al
  // titolo; negli altri formati restano sotto, a tutta larghezza.
  // In orizzontale le due colonne sono strette: l'archetipo accanto al nome
  // costringerebbe a troncare entrambi, ed e gia nella colonna Metagame qui
  // di fianco. Negli altri formati c'e spazio e resta.
  const top8 = _data.standings.slice(0, 8).map((s, i) => ({
    left: `${i + 1}. ${s.name}`,
    right: wide ? '' : (s.archetype || ''),
  }));

  if (narrow) {
    // 9:16: due blocchi impilati a tutta larghezza. Affiancarli su una scheda
    // stretta e alta sprecava meta altezza e troncava i nomi.
    const full = w - pad * 2;
    const listH = drawList(ctx, 'TOP 8', top8, pad, y, full, bottom, scale);
    drawBars(ctx, 'METAGAME', _data.meta.slice(0, 8), pad, y + listH + 54 * scale, full, bottom, scale);
  } else {
    const listsX = wide ? pad * 2 + headW : pad;
    const listsY = wide ? headTop + 40 * scale : y;
    const listsW = wide ? w - listsX - pad : w - pad * 2;
    const colW = (listsW - colGap) / 2;
    drawList(ctx, 'TOP 8', top8, listsX, listsY, colW, bottom, scale);
    drawBars(ctx, 'METAGAME', _data.meta.slice(0, 8), listsX + colW + colGap, listsY, colW, bottom, scale);
  }

  // ── Piede ──
  ctx.fillStyle = MUTED;
  ctx.font = `500 ${Math.round(20 * scale)}px Inter, system-ui, sans-serif`;
  ctx.fillText(location.host, pad, h - pad + 8 * scale);

  return canvas;
}

function drawList(ctx, title, items, x, y, colW, bottom, scale) {
  ctx.fillStyle = MUTED;
  ctx.font = `700 ${Math.round(20 * scale)}px Inter, system-ui, sans-serif`;
  ctx.fillText(title, x, y);
  let cy = y + 38 * scale;
  const rowH = 44 * scale;
  for (const item of items) {
    if (cy + rowH > bottom) break;
    ctx.fillStyle = PANEL;
    roundRect(ctx, x, cy - 24 * scale, colW, rowH - 8 * scale, 10 * scale);
    ctx.fill();

    // La colonna di destra si misura per prima e quella di sinistra prende
    // quello che resta: con due quote fisse i due testi si sovrapponevano
    // appena il nome era lungo e la colonna stretta.
    let right = '';
    let rightW = 0;
    if (item.right) {
      ctx.font = `500 ${Math.round(18 * scale)}px Inter, system-ui, sans-serif`;
      right = fitText(ctx, item.right, colW * 0.38);
      rightW = ctx.measureText(right).width;
    }
    const gap = 10 * scale;
    ctx.fillStyle = INK;
    ctx.font = `700 ${Math.round(22 * scale)}px Inter, system-ui, sans-serif`;
    ctx.fillText(fitText(ctx, item.left, colW - 28 * scale - rightW - gap), x + 14 * scale, cy + 2 * scale);

    if (right) {
      ctx.fillStyle = MUTED;
      ctx.font = `500 ${Math.round(18 * scale)}px Inter, system-ui, sans-serif`;
      ctx.textAlign = 'right';
      ctx.fillText(right, x + colW - 14 * scale, cy + 2 * scale);
      ctx.textAlign = 'left';
    }
    cy += rowH;
  }
  return cy - y;
}

function drawBars(ctx, title, rows, x, y, colW, bottom, scale) {
  ctx.fillStyle = MUTED;
  ctx.font = `700 ${Math.round(20 * scale)}px Inter, system-ui, sans-serif`;
  ctx.fillText(title, x, y);
  if (!rows.length) {
    ctx.fillStyle = MUTED;
    ctx.font = `500 ${Math.round(20 * scale)}px Inter, system-ui, sans-serif`;
    ctx.fillText('Archetipi non disponibili', x, y + 40 * scale);
    return;
  }
  const max = Math.max(...rows.map((r) => r.players));
  let cy = y + 38 * scale;
  const rowH = 44 * scale;
  for (const r of rows) {
    if (cy + rowH > bottom) break;
    const barW = Math.max(6 * scale, (colW * 0.9) * (r.players / max));
    ctx.fillStyle = 'rgba(198, 255, 61, 0.18)';
    roundRect(ctx, x, cy - 24 * scale, barW, rowH - 8 * scale, 10 * scale);
    ctx.fill();

    ctx.fillStyle = INK;
    ctx.font = `600 ${Math.round(21 * scale)}px Inter, system-ui, sans-serif`;
    ctx.fillText(fitText(ctx, r.archetype, colW - 56 * scale), x + 14 * scale, cy + 2 * scale);

    ctx.fillStyle = ACCENT;
    ctx.font = `700 ${Math.round(20 * scale)}px Inter, system-ui, sans-serif`;
    ctx.textAlign = 'right';
    ctx.fillText(`${r.players}`, x + colW - 14 * scale, cy + 2 * scale);
    ctx.textAlign = 'left';
    cy += rowH;
  }
}

/* ── Pagina ────────────────────────────────────────────────── */

function redraw() {
  const canvas = $('#coverCanvas');
  drawCard(canvas, _size);
  const { w, h, label } = SIZES[_size];
  $('#coverMeta').textContent = `${w} × ${h} px — ${label}`;
}

function download() {
  const canvas = $('#coverCanvas');
  const slug = String(_data.name).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  const a = document.createElement('a');
  a.download = `${slug || 'torneo'}-${_size}.png`;
  a.href = canvas.toDataURL('image/png');
  a.click();
}

async function load() {
  const tid = new URLSearchParams(location.search).get('t');
  const host = $('#coverPage');
  if (!tid) { host.innerHTML = '<p class="empty">Torneo non indicato.</p>'; return; }

  let results;
  try { results = await apiGet(`/tournaments/${tid}/public-results`); }
  catch (err) { host.innerHTML = `<p class="empty">${esc(err.message)}</p>`; return; }
  if (!results.standings_public) {
    host.innerHTML = '<p class="empty">La classifica di questo torneo non è pubblica: non c\'è nulla da pubblicare.</p>';
    return;
  }
  // Il metagame può mancare (archetipi non compilati): la scheda regge lo stesso.
  const meta = await apiGet(`/tournaments/${tid}/public-meta`).catch(() => []);

  _data = {
    name: results.name,
    format: results.format,
    starts_on: results.starts_on,
    players: results.standings.length,
    standings: results.standings,
    meta,
  };

  document.title = `${results.name} — Coverage`;
  $('#coverTitle').textContent = results.name;
  $('#coverSizes').innerHTML = Object.entries(SIZES).map(([k, v]) =>
    `<button class="chip" type="button" data-size="${k}" aria-pressed="${k === _size}">${esc(v.label)}</button>`).join('');
  $('#coverSizes').querySelectorAll('[data-size]').forEach((b) =>
    b.addEventListener('click', () => {
      _size = b.dataset.size;
      $('#coverSizes').querySelectorAll('[data-size]').forEach((x) =>
        x.setAttribute('aria-pressed', x === b));
      redraw();
    }));
  $('#coverDownload').addEventListener('click', download);
  $('#coverLink').href = `history.html?t=${tid}`;
  $('#coverTools').style.display = '';
  redraw();
}

onReady(() => { updateAuthNav(); load(); });
