# Plan

## Goal

Turn "what should we watch?" in a two-person household group text into a decision in under 5 minutes, using only films from a shared Letterboxd watchlist.

**v1 success (proposed targets):** 8 movie nights in a row decided through the agent, a median under 5 minutes from first message to locked pick, and both people rating the pick "good" at least 75% of the time.

**Out of scope for v1:** social signals (podcasts, followed accounts) as a "why now" signal. That's planned for v2.

## The experience

1. **Kickoff.** Either person texts the agent, with or without a hint: "movie tonight?", "something scary", "newly streaming, under 2 hours".
2. **Picks.** One intro line, then 4-5 messages, one per film. Each has the title and year, a trailer link, the Letterboxd rating, the runtime, where to watch it (streaming on the household's services, otherwise the rent/buy price) and a sentence or two on why it fits tonight.
3. **Reactions.** Each person reacts with 🥇 🥈 🥉 or 🚫.
4. **Nudge.** If only one person has reacted after 20 minutes, the agent sends one reminder.
5. **Winner.** Once both have reacted, or someone texts "call it", the agent posts the winner, the scores and where to press play.
6. **Afterward.** The next morning it asks one question: "Good pick? 👍 / 👎".

Text controls: "more" sends another set, "swap 3" replaces one film, and "call it" closes voting.

Services counted as "streaming tonight": Netflix, Max, Prime Video, Apple TV, Peacock, YouTube Premium.

## Rules

Implemented in `movie_night/rules.py` and covered by tests.

| Rule | How it works |
|---|---|
| Points | 🥇 3, 🥈 2, 🥉 1, no reaction 0 |
| One of each | One of each medal per person per session; a second 🥇 moves the first |
| Veto | 🚫 removes the film; one per person per session |
| No back-to-back vetoes | Whoever vetoed last session can't veto this one |
| Tie-break 1 | The higher lower score wins (2+2 beats 3+1) |
| Tie-break 2 | The person who missed their top pick last time wins |
| Tie-break 3 | The higher Letterboxd rating wins |
| Everything vetoed | A fresh set is sent and the veto record is kept |
| Changed mind | Reaction changes count until the winner is posted |

## Architecture

Linq delivers messages and reactions to a small hosted service as webhooks. A ranker picks candidates from the film store using the hint, the runtime, availability and past reactions. The LLM writes the messages, and the rules engine tallies and logs every vote. A daily job syncs the watchlist and TMDB data.

## Metrics and evals

| Metric | Definition | Proposed target |
|---|---|---|
| Time to decision (north star) | Median minutes from kickoff to winner | Under 5 |
| Decision rate | Share of sessions that end in a winner | 90%+ |
| Good-pick rate (guardrail) | Both people answer 👍 the next morning | 75%+ |
| Ranking quality | Winner was the agent's #1 or #2 pick (hit@2) | Rising over 8 weeks |
| Fairness | Each person's top pick wins about half the time | 40-60% |
| Veto rate | Films vetoed per session | Falling |

Evals run before every prompt or ranking change:

- **Hint understanding:** about 50 hints, each paired with the filters it should produce.
- **Grounding:** every fact in a pick message matches the source data. Checked by code, target 100%.
- **Why-it-was-picked faithfulness:** an LLM judge, calibrated against hand labels.
- **Offline ranking replay:** replay logged sessions against ranking changes.

## Milestones

0. **M0: Linq spike (gate).** Group chat, a test pick with a trailer link, reactions arriving as emoji, the real price. See `docs/m0-linq-spike.md`.
1. **M1: Film data.** Daily watchlist sync, TMDB enrichment (trailer, runtime, genres, US streaming/rent/buy), the Letterboxd rating, and a daily availability snapshot.
2. **M2: Agent v1, one tester.** Kickoff, hint parsing, picks with reasons, tally, winner.
3. **M3: Household beta.** Two to three weeks of real movie nights, every session logged.
4. **M4: Evals and learning.** Eval sets from real sessions; tune ranking on reactions and ratings.
5. **M5 (v2): Social signals.**

## Risks

| Risk | Fallback |
|---|---|
| Custom emoji reactions don't come through | Map to standard tapbacks, or accept text replies |
| No group chats on the free line, or high pricing | BlueBubbles on an always-on Mac |
| A Letterboxd layout change breaks the sync | Fail loudly; the CSV export as a manual backup |
| Letterboxd terms | Read only the household's own public list, once a day, at low volume |
| TMDB terms | Personal, non-commercial use with attribution |
