# Decisions

Newest first. Each entry says what was decided and why.

## 2026-11-10: Picks are rich, standard iMessage messages

Each pick is a short text (title and year, then runtime, genres and where to watch, then one line on why) followed by its trailer as a standalone link, which iMessage turns into a preview card. A link inside the text gets no preview (seen live in M0). Chuck wants this richer, standard format, and will revisit once real multi-pick sessions run. A veto counts as a 👎 tapback or a 🚫 emoji.

## 2026-11-09: The vote is code, not the LLM

The LLM writes messages and reads hints. Winners come from `movie_night/rules.py`. Every result is then explainable ("Bravo won 2+2 over Alpha's 3+1"), replayable from the log, and testable.

## 2026-11-09: Tie-break on the lower individual score

When totals tie, the film whose lower score is higher wins: 2+2 beats 3+1. For two people choosing together, a film both like beats one only one person loves. Next comes whoever missed their top pick last time, then the Letterboxd rating.

## 2026-11-09: No back-to-back vetoes

A veto is powerful with only 4-5 films on the table. Allowing one per session, and none in the session after you used one, keeps it for real dealbreakers.

## 2026-11-09: iMessage via Linq, with BlueBubbles as the fallback

The household already plans movie nights in iMessage, so the agent goes where the conversation already is. Linq offers a hosted iMessage API with group chats and reactions. BlueBubbles on an always-on Mac is the fallback if group chats, custom emoji reactions or pricing don't work out (M0 decides).

## 2026-11-09: The agent speaks only when asked

There's no scheduled "movie tonight?" message. A session starts only when someone in the household kicks one off, plus one nudge and one next-morning rating question.

## 2026-11-09: Picks come only from the shared watchlist

The watchlist is what the household has already said it wants to see. The agent's job is to choose from it, not to add to it.
