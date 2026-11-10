# Decisions

Newest first. Each entry says what was decided and why.

## 2026-11-10: Search and "more like this" use TMDB keywords, not an LLM

"Delo, spy movies" matches TMDB's topic tags (with a small synonym list), and only tags that films on the watchlist actually carry count. "Something like The Wicker Man" looks the title up on TMDB and ranks the watchlist by shared tags (rarer tags count more, generic ones like "based on novel or book" don't count), shared genres, and TMDB's own related films. Every pick says why ("Shares: folk horror, human sacrifice"). It's predictable and testable; an LLM can widen the phrasing it understands later. Films on household services come before rentals.

## 2026-11-10: Host on Railway

Chuck picked Railway: it deploys from the GitHub repo on every merge, with no command line, so features ship as soon as a PR is approved. One container runs the agent, the daily sync and a health check, with a volume at /data. It replaces "poll first, host later". The agent still polls; webhooks come later.

## 2026-11-10: Poll first, host later

Chuck chose to defer hosting. M2 polls the group chat every few seconds from wherever it runs, so real sessions can be tried before paying for a server or setting up webhooks.

## 2026-11-10: v1 reads hints with keywords, not an LLM

"short", "under 2 hours", "funny", "no horror", "nothing heavy", "ok to rent" cover the common asks and are fully testable. The "why" line is the Letterboxd rating for now. An LLM can take over hint parsing and the why line later without touching the vote.

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

## 2026-11-10: One household taste profile, scored in plain arithmetic

The Letterboxd account is shared and its ratings are a joint verdict, so there is one profile, not one per person. Each rated film weighs in from +1 (5 stars) to -1 (1 star), plus 0.5 for a heart. A film's score is its rarity-weighted keyword overlap with that profile, plus how the household rates its genres, plus a boost when TMDB recommends it from a loved film. No model is trained: every pick can name the loved films it resembles, and individual tastes show up later in medals and vetoes.

## 2026-11-10: 3 watchlist picks plus 2 wildcards (supersedes "only the watchlist")

A wildcard is a film the household hasn't rated and hasn't saved. It is labeled as one, so the watchlist stays the default.

## 2026-11-10: Full rating history comes from the Letterboxd data export

Letterboxd's bot check allows only the first page of /films/ (the newest 72), so the full history comes from the export the account owner downloads (Settings > Data). That is also the more honest route than working around the block.

## 2026-11-10: A pick is one message with its poster; trailers come on 👀

Each pick is one Linq message: the TMDB poster as a media part, then the short text. Votes on either part count. Trailers are no longer sent with every pick, because five link cards bury the picks. Reacting 👀 on a pick makes Delo reply in a thread under that pick with the trailer card, once per film. 👀 is a request, not a vote. A Letterboxd link card would also show artwork, but a link part has to be the only part in its message, so it would split each pick in two again.

## 2026-11-10: Pick text: a film-specific emoji, bold title, bullets, and an italic source label

Every pick used to open with 🎬, which told you nothing. Now Claude chooses one emoji per film (a setting, object or motif, never a spoiler). It is cached in data/emoji.json, and a keyword or genre map stands in when there's no key or the call fails. The title is bold and each reason is its own bullet. The last line, in italics, says "From your watchlist" or "🃏 Wildcard: not on your watchlist", so the 3 + 2 split is visible on every pick. iMessage always shows an attachment and its text as separate bubbles, so the poster sits directly above the text as part of the same message.
