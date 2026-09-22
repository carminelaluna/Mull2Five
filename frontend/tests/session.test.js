/**
 * session.test.js — Il modulo della sessione: token, chiamate all'API e rinnovo.
 *
 * I token qui sono finti (la firma non conta: la verifica la fa il server),
 * fetch è sostituita da una spia.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  apiRequest, clearToken, decodeToken, errorText, getSession, getToken, refreshSession, setToken,
} from '../js/session.js';

/* Un token con le rivendicazioni date: intestazione finta, firma finta. */
function fakeToken(claims) {
  const body = btoa(JSON.stringify(claims)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  return `header.${body}.signature`;
}

const now = () => Math.floor(Date.now() / 1000);

function response(status, body = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe('il token', () => {
  it('si legge e si decodifica', () => {
    expect(getToken()).toBe(null);
    setToken(fakeToken({ sub: '7', email: 'a@b.it', exp: now() + 100 }));
    expect(decodeToken().email).toBe('a@b.it');
    expect(getSession().sub).toBe('7');
    clearToken();
    expect(getSession()).toBe(null);
  });

  it('scaduto non è una sessione', () => {
    setToken(fakeToken({ sub: '7', exp: now() - 10 }));
    expect(decodeToken()).not.toBe(null);
    expect(getSession()).toBe(null);
  });

  it('rotto non rompe la pagina', () => {
    setToken('non-e-un-token');
    expect(decodeToken()).toBe(null);
    expect(getSession()).toBe(null);
  });
});

describe('gli errori del server', () => {
  it('sono una frase o la lista dei campi non validi', () => {
    expect(errorText('Torneo non trovato')).toBe('Torneo non trovato');
    expect(errorText([{ msg: 'campo obbligatorio' }, { msg: 'troppo lungo' }]))
      .toBe('campo obbligatorio · troppo lungo');
    expect(errorText(undefined, 'Errore')).toBe('Errore');
  });
});

describe('apiRequest', () => {
  it('manda il token e restituisce il JSON', async () => {
    setToken(fakeToken({ sub: '1', exp: now() + 100 }));
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(response(200, { id: 3 }));
    const data = await apiRequest('/tournaments/3');
    expect(data).toEqual({ id: 3 });
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/tournaments/3');
    expect(opts.headers.Authorization).toMatch(/^Bearer /);
  });

  it('senza sessione non manda intestazioni di accesso', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(response(204));
    expect(await apiRequest('/tournaments')).toBe(null);
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe(undefined);
  });

  it("porta con sé lo stato dell'errore", async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(response(409, { detail: 'Email già registrata' }));
    await expect(apiRequest('/auth/register', { method: 'POST' })).rejects.toMatchObject({
      message: 'Email già registrata', status: 409,
    });
  });

  it('con requireLogin un 401 chiude la sessione', async () => {
    setToken(fakeToken({ sub: '1', exp: now() + 100 }));
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(response(401, { detail: 'scaduto' }));
    await expect(apiRequest('/auth/me', { requireLogin: true })).rejects.toThrow();
    expect(getToken()).toBe(null);
  });

  it('senza requireLogin un 401 è solo un errore', async () => {
    setToken(fakeToken({ sub: '1', exp: now() + 100 }));
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(response(401, { detail: 'scaduto' }));
    await expect(apiRequest('/tournaments/1/my-registration')).rejects.toThrow();
    expect(getToken()).not.toBe(null);
  });
});

describe('il rinnovo del token', () => {
  it('non chiede niente a un token appena emesso', async () => {
    setToken(fakeToken({ sub: '1', iat: now(), exp: now() + 3600 }));
    const fetchMock = vi.spyOn(globalThis, 'fetch');
    expect(await refreshSession()).toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('dopo mezza giornata ne chiede uno nuovo', async () => {
    const old = fakeToken({ sub: '1', iat: now() - 13 * 3600, exp: now() + 3600 });
    setToken(old);
    const fresh = fakeToken({ sub: '1', iat: now(), exp: now() + 86400 });
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(response(200, { access_token: fresh }));
    expect(await refreshSession()).toBe(true);
    expect(getToken()).toBe(fresh);
  });

  it('se il server rifiuta il token, la sessione si chiude', async () => {
    setToken(fakeToken({ sub: '1', iat: now() - 13 * 3600, exp: now() + 3600 }));
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(response(401));
    expect(await refreshSession()).toBe(false);
    expect(getToken()).toBe(null);
  });
});
