import { describe, it, expect } from 'vitest';
import { urlBase64ToUint8Array } from '../js/push.js';

describe('push — urlBase64ToUint8Array', () => {
  it('decodifica base64url in Uint8Array della lunghezza attesa', () => {
    // "hello" in base64 standard = "aGVsbG8="; in base64url senza padding = "aGVsbG8"
    const out = urlBase64ToUint8Array('aGVsbG8');
    expect(out).toBeInstanceOf(Uint8Array);
    expect([...out]).toEqual([...'hello'].map((c) => c.charCodeAt(0)));
  });

  it('gestisce i caratteri base64url - e _ (al posto di + e /)', () => {
    // Byte che in base64 standard producono + e / → in base64url diventano - e _
    const bytes = [0xfb, 0xff, 0xbf];           // base64 standard: "+/+/" → url: "-_-_"
    const b64url = btoa(String.fromCharCode(...bytes))
      .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
    expect(b64url).toContain('-');
    expect(b64url).toContain('_');
    const out = urlBase64ToUint8Array(b64url);
    expect([...out]).toEqual(bytes);
  });
});
