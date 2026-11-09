# movie-night-agent

An agent that lives in a household iMessage group text and turns "what should we watch?" into a decision in under five minutes, using only films from a shared Letterboxd watchlist.

Someone texts the agent ("movie tonight?", "something scary under 2 hours"). It sends 4-5 picks from the watchlist as separate messages, each person reacts with 🥇 🥈 🥉 or 🚫, and deterministic rules pick the winner.

**Status:** early build. M0, the messaging spike, is in progress. See [PLANNING.md](PLANNING.md).

## What's here

| Path | What it does |
|---|---|
| `movie_night/rules.py` | The vote rules: medal points, vetoes, no back-to-back vetoes, fairness tie-breaks. Plain code, not the LLM, so every result can be explained and replayed. |
| `movie_night/watchlist.py` | Reads a public Letterboxd watchlist (politely: one page a second, once a day). |
| `scripts/m0_spike.py` | The Linq group-chat and reaction spike. |
| `docs/m0-linq-spike.md` | What M0 has to prove, and its results. |
| `DECISIONS.md` | Why things are the way they are. |

## Run the tests

```
python3 -m unittest
```

Python 3.11+ and the standard library only, so far.

## Data and secrets

API keys and household data (phone numbers, session logs) never go in this repo. Film data comes from Letterboxd and [TMDB](https://www.themoviedb.org/). This product uses the TMDB API but is not endorsed or certified by TMDB.
