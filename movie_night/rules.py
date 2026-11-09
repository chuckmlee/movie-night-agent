"""Deterministic vote rules for one movie-night session.

The LLM never decides the winner. Everything here is plain code so every
result can be explained and replayed from the session log.

Rules (see PLANNING.md):
  * Points: gold = 3, silver = 2, bronze = 1, no reaction = 0.
  * One of each medal per person per session; a second gold moves the first.
  * A veto removes the film. One veto per person per session.
  * No back-to-back vetoes: someone who vetoed last session cannot veto now.
  * Tie-break 1: higher lower-individual-score wins (2+2 beats 3+1).
  * Tie-break 2: the person who didn't get their top pick last time wins.
  * Tie-break 3: higher Letterboxd rating.
  * Everything vetoed: no winner; the caller sends a fresh set.
  * Reaction changes count until the winner is posted (the caller stops
    feeding events once the session is closed).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Reaction(str, Enum):
    GOLD = "gold"
    SILVER = "silver"
    BRONZE = "bronze"
    VETO = "veto"


POINTS = {Reaction.GOLD: 3, Reaction.SILVER: 2, Reaction.BRONZE: 1}


@dataclass(frozen=True)
class Film:
    film_id: str
    title: str
    letterboxd_rating: float | None = None


@dataclass
class ReactionEvent:
    person: str
    film_id: str
    reaction: Reaction
    removed: bool = False  # True when the person takes the reaction back


@dataclass
class History:
    """What happened last session, for the fairness rules."""

    vetoed_last_session: set[str] = field(default_factory=set)
    # People whose top pick did not win last session.
    missed_top_pick_last_session: set[str] = field(default_factory=set)


@dataclass
class FilmScore:
    film: Film
    per_person: dict[str, int]
    vetoed_by: list[str]

    @property
    def total(self) -> int:
        return sum(self.per_person.values())


@dataclass
class Result:
    winner: Film | None
    scores: list[FilmScore]  # sorted best first, vetoed films last
    rejected: list[tuple[ReactionEvent, str]]  # events ignored, with reason
    tie_break: str | None = None  # which rule decided it, if any
    all_vetoed: bool = False


class Session:
    def __init__(self, films: list[Film], people: list[str], history: History | None = None):
        if not films:
            raise ValueError("a session needs at least one film")
        self.films = {f.film_id: f for f in films}
        self.order = [f.film_id for f in films]
        self.people = list(people)
        self.history = history or History()
        # person -> reaction -> film_id
        self.state: dict[str, dict[Reaction, str]] = {p: {} for p in people}
        self.rejected: list[tuple[ReactionEvent, str]] = []

    def can_veto(self, person: str) -> bool:
        return person not in self.history.vetoed_last_session

    def apply(self, event: ReactionEvent) -> None:
        if event.person not in self.state:
            self.rejected.append((event, "not a member of this session"))
            return
        if event.film_id not in self.films:
            self.rejected.append((event, "film is not in this session"))
            return
        mine = self.state[event.person]
        if event.removed:
            if mine.get(event.reaction) == event.film_id:
                del mine[event.reaction]
            return
        if event.reaction is Reaction.VETO and not self.can_veto(event.person):
            self.rejected.append((event, "vetoed last session; no back-to-back vetoes"))
            return
        # One reaction per film per person: a new reaction on the same film
        # replaces whatever they gave it before.
        for r, fid in list(mine.items()):
            if fid == event.film_id:
                del mine[r]
        # One of each per session: giving a medal again moves it.
        mine[event.reaction] = event.film_id

    def tally(self) -> Result:
        scores: list[FilmScore] = []
        for fid in self.order:
            per_person = {p: 0 for p in self.people}
            vetoed_by = []
            for p, mine in self.state.items():
                for r, rfid in mine.items():
                    if rfid != fid:
                        continue
                    if r is Reaction.VETO:
                        vetoed_by.append(p)
                    else:
                        per_person[p] = POINTS[r]
            scores.append(FilmScore(self.films[fid], per_person, vetoed_by))

        alive = [s for s in scores if not s.vetoed_by]
        dead = [s for s in scores if s.vetoed_by]
        if not alive:
            return Result(None, scores, list(self.rejected), all_vetoed=True)

        def low(s: FilmScore) -> int:
            return min(s.per_person.values()) if s.per_person else 0

        def favoured(s: FilmScore) -> int:
            # 1 if this film is the top pick of someone who missed out last time.
            for p in self.history.missed_top_pick_last_session:
                if s.per_person.get(p) == POINTS[Reaction.GOLD]:
                    return 1
            return 0

        def rating(s: FilmScore) -> float:
            return s.film.letterboxd_rating or 0.0

        keys = [
            ("total", lambda s: s.total),
            ("tie-break 1: higher lower score", low),
            ("tie-break 2: person who missed their top pick last time", favoured),
            ("tie-break 3: higher Letterboxd rating", rating),
        ]
        ranked = sorted(alive, key=lambda s: tuple(k(s) for _, k in keys), reverse=True)

        tie_break = None
        if len(ranked) > 1:
            a, b = ranked[0], ranked[1]
            for name, k in keys:
                if k(a) != k(b):
                    tie_break = None if name == "total" else name
                    break
            else:
                tie_break = "tie-break 4: earlier in the pick list"
        return Result(ranked[0].film, ranked + dead, list(self.rejected), tie_break)

    def top_picks(self) -> dict[str, str | None]:
        """Each person's gold film, for next session's tie-break 2."""
        return {p: self.state[p].get(Reaction.GOLD) for p in self.people}
