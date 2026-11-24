"""
registration_qr.py — Il QR che porta all'iscrizione di un torneo.

L'organizzatore lo stampa e lo appende al banco o lo mette sui social: chi lo
inquadra arriva sulla pagina del torneo con la finestra d'iscrizione già aperta
(`iscriviti=1`, la legge event.js). Il QR contiene solo l'indirizzo pubblico
della pagina, niente che non sia già visibile a tutti.
"""
import io

import segno

KINDS = {"svg": "image/svg+xml", "png": "image/png"}


def registration_url(base_url: str, tournament_id: int) -> str:
    return f"{base_url.rstrip('/')}/event.html?id={tournament_id}&iscriviti=1"


def qr_image(url: str, kind: str) -> bytes:
    """Il QR in SVG (si ingrandisce senza perdere niente) o in PNG grande da stampare.

    Correzione d'errore «M»: regge un QR stampato un po' sciupato o fotografato
    storto, e con indirizzi così corti resta comunque piccolo e fitto il giusto.
    """
    code = segno.make(url, error="m", micro=False)
    buffer = io.BytesIO()
    if kind == "svg":
        code.save(buffer, kind="svg", scale=10, border=4, xmldecl=False, svgclass=None, lineclass=None)
    else:
        code.save(buffer, kind="png", scale=20, border=4)
    return buffer.getvalue()
