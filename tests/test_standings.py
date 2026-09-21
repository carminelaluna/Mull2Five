"""
test_standings.py — Spareggi per gioco, su tornei scritti a mano.

I valori attesi sono calcolati a mano dai regolamenti (vedi services/standings.py):
se cambiano, è cambiata la regola, non un dettaglio.
"""
from backend.app.services.standings import Match, Player, compute_standings


def _order(rows):
    return [r["name"] for r in rows]


def _by_name(rows):
    return {r["name"]: r for r in rows}


# ── Magic Tournament Rules (anche Lorcana e Star Wars Unlimited) ──


def _mtr_tournament():
    players = [Player(i, n) for i, n in enumerate("ABCD", start=1)]
    a, b, c, d = 1, 2, 3, 4
    matches = [
        Match(a, b, "A", 2, 0), Match(c, d, "A", 2, 0),   # turno 1
        Match(a, c, "A", 2, 1), Match(b, d, "A", 2, 0),   # turno 2
    ]
    return players, matches


def test_mtr_game_win_breaks_a_tie_on_omw():
    rows = compute_standings(*_mtr_tournament(), system="mtr")
    # B e C: 3 punti e OMW 66,7% entrambi; C ha vinto più giochi (60% contro 50%).
    assert _order(rows) == ["A", "C", "B", "D"]
    r = _by_name(rows)
    assert (r["C"]["opponent_match_win_percentage"], r["C"]["game_win_percentage"]) == (66.7, 60.0)
    assert (r["B"]["opponent_match_win_percentage"], r["B"]["game_win_percentage"]) == (66.7, 50.0)
    assert r["A"]["opponent_game_win_percentage"] == 55.0   # B 50% e C 60%


def test_mtr_percentages_never_go_below_a_third():
    r = _by_name(compute_standings(*_mtr_tournament(), system="mtr"))
    # D non ha vinto né un match né un gioco: per gli spareggi vale 33,3%, non 0.
    assert r["D"]["match_win_percentage"] == 33.3
    assert r["D"]["game_win_percentage"] == 33.3


def test_mtr_a_bye_is_a_win_but_not_an_opponent():
    players = [Player(1, "A"), Player(2, "B"), Player(3, "C")]
    matches = [Match(1, None, None), Match(2, 3, "A", 2, 0)]
    r = _by_name(compute_standings(players, matches, system="mtr"))
    assert (r["A"]["points"], r["A"]["record"]) == (3, "1/0/0")
    # Senza avversari veri l'OMW di A è 0, e il bye non entra nell'OMW di nessuno.
    assert r["A"]["opponent_match_win_percentage"] == 0.0
    assert r["B"]["opponent_match_win_percentage"] == 33.3


# ── One Piece ──


def test_onepiece_excludes_byes_from_the_win_rate():
    players = [Player(1, "A"), Player(2, "B"), Player(3, "C")]
    matches = [
        Match(1, 2, "A", 1, 0), Match(3, None, None),   # turno 1: bye a C
        Match(3, 1, "A", 1, 0), Match(2, None, None),   # turno 2: bye a B
    ]
    rows = compute_standings(players, matches, system="onepiece")
    # A e B a 3 punti: A ha vinto la sua partita vera, B ha solo il bye.
    assert _order(rows) == ["C", "A", "B"]
    r = _by_name(rows)
    assert r["C"]["match_win_percentage"] == 100.0   # 1 su 1, il bye non conta
    assert r["B"]["match_win_percentage"] == 33.0    # 0 su 1, portato al minimo 0,33
    assert r["A"]["opponent_match_win_percentage"] == 66.5   # media di B 0,33 e C 1,0


# ── Pokémon ──


def test_pokemon_bye_is_not_a_win_for_win_percentage():
    players = [Player(1, "A"), Player(2, "B"), Player(3, "C"), Player(4, "D", dropped=True)]
    matches = [
        Match(1, 2, "A", 2, 0), Match(3, 4, "A", 2, 0),   # turno 1, poi D lascia
        Match(1, 3, "A", 2, 1), Match(2, None, None),     # turno 2: bye a B
    ]
    rows = compute_standings(players, matches, system="pokemon", total_rounds=2)
    r = _by_name(rows)
    # B ha 3 punti ma solo dal bye: la sua win % resta al minimo del 25%.
    assert r["B"]["match_win_percentage"] == 25.0
    # A 6 punti, poi B e C a 3: passa B per Op Win % (A 100% contro la media di C, 62,5%).
    assert _order(rows) == ["A", "B", "C", "D"]
    assert r["C"]["opponent_match_win_percentage"] == 62.5


def test_pokemon_caps_players_who_dropped_at_75_percent():
    players = [Player(1, "X", dropped=True), Player(2, "Y")]
    matches = [Match(1, 2, "A", 2, 0)]
    r = _by_name(compute_standings(players, matches, system="pokemon", total_rounds=3))
    assert r["X"]["match_win_percentage"] == 75.0   # 1 su 1, ma ha lasciato
    assert r["Y"]["opponent_match_win_percentage"] == 75.0


def test_pokemon_head_to_head_settles_a_full_tie():
    # Quattro giocatori, tutti 1-1 con gli stessi spareggi; A ha battuto B.
    players = [Player(2, "B"), Player(1, "A"), Player(3, "C"), Player(4, "D")]
    matches = [
        Match(1, 2, "A", 2, 0), Match(3, 4, "A", 2, 0),
        Match(2, 3, "A", 2, 0), Match(4, 1, "A", 2, 0),
    ]
    rows = compute_standings(players, matches, system="pokemon", total_rounds=2)
    names = _order(rows)
    assert names.index("A") < names.index("B")
