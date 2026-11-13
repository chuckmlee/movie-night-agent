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

## 2026-11-10: Claude chooses picks for asks with nuance; code still builds the shortlist

"Like The Devils but less shocking, as intellectually rich" needs judgment that keyword overlap can't supply. When an ask carries comparisons or tone words (`ask.is_nuanced`), code builds a shortlist of 50 eligible films: the closest keyword matches to any named film first, then the household's best-scored films, with about a fifth of them wildcards. Claude Opus 5.5, at low effort, chooses up to 5 from that list and gives each a one-line reason grounded in the synopsis and tags. Ids outside the shortlist are dropped. Streaming filters, exclusions and the watchlist/wildcard labels stay in code. Plain asks never reach Claude. With no key, or a failed or refused call, the keyword matcher answers as before. Each ask costs about 2–4¢.

## Follow-ups narrow the last ask (Nov 10)

While picks are open, a message that opens like an instruction ("limit to Catholic themes", "shorter",
"less bleak", "no horror"), or one addressed to Delo with "only"/"limit"/"instead", is joined to the
last ask as a "Follow-up:" line and sent to Claude, even without a tone word. The new picks replace the
open ones. Other chat between the two of them is still ignored, and with no picks open a follow-up is
ignored too. "Like X but less Y" now reads the title as X alone, so the TMDB lookup finds X.

## Vetoes bring a replacement, and can say why (Nov 11)

Suggested by Chuck. A veto, either a 👎 or a reply on a pick like "veto, too bleak", "nah, too long" or
"no war movies", brings one replacement pick, and the replacement can't be vetoed. Claude gets the reason,
or when there's only a 👎, is told to infer it from the picks that were kept. The reason is also added to
the session's ask, so later follow-ups keep avoiding it. Without a reply link, a message that starts with
"veto" applies to the pick it names (Nov 11: matched loosely, so "fire walk with me" finds "Twin Peaks: Fire Walk with Me"); if it names none, Delo asks which one instead of guessing. Fairness: whoever vetoed last session
sits out, unless everyone vetoed, in which case nobody owes anything.

## A blended quality score beside the taste fit (Nov 11)

Chuck wants one consensus score built from Letterboxd, IMDb, Rotten Tomatoes, Metacritic and the trusted
circle. Each source becomes a percentile among the films Delo knows, so their different scales compare.
The weights are Letterboxd 30%, critics 30% (the mean of the Tomatometer and Metacritic), IMDb 15% (only
with 500+ votes) and circle 25% (people who loved it, with diminishing returns). A missing source is
skipped, not counted as zero, and `sources` records how many were used. Picks rank on 60% taste fit and
40% quality, so a critics' favorite that doesn't suit the household doesn't win on reputation alone.
Ratings come from OMDb (OMDB_API_KEY, 900 calls per nightly sync, refreshed every 30 days). How the score
appears in messages is undecided, so it isn't shown yet.

## One score and one highlight on each pick (Nov 11)

Chuck's call: one number with one highlight that explains it. The number is the quality score only. Fit
is already shown in words ("Because you loved…"), and a fit percentage would mean little and move
every night. The highlight is the circle's love if anyone loved the film, then a sharp critics-vs-audience
split (35+ percentile points), then the best source. A score built on one source shows that source as-is
("★ 4.1 on Letterboxd") instead of a number that looks more certain than it is. Wildcards get the line too.

## Pick layout (Nov 11)

Agreed with Chuck. Each pick is the poster, then three blocks separated by blank lines. The header has
the emoji and bold title (year not bold), the score line, then the runtime and two genres. The second
block is "Streaming on Max" or "Rent on Apple TV". The third is the reason as one plain sentence, with a
friend's quote in italics under it. Only wildcards get the italic 🃏 label, since the intro already counts
watchlist picks. The score line stays on one line (38 characters or fewer), so the highlight is
"critics' favorite" with no figure. When the pick already quotes someone in the circle, the highlight
skips the circle so it isn't said twice.

## Directors, cast, country and language (Nov 11)

The sync stores TMDB credits for each film: its director(s), the top 5 cast, its production countries and
its original language. Films cached earlier get them in the next sync. Claude sees them when it picks, so
"no David Lynch" and "something Korean" work. Without Claude, a name in an ask matches as well: "lynch
movies" by director, "something with Cate Blanchett" by cast. A surname counts on its own only when it
belongs to a single person in the cache. "no/not/without <name>" removes that person's films from
every kind of pick, including veto replacements. More specific genres come from TMDB tags for now, and
Letterboxd nanogenres are a possible next step.

## Don't offer the same film over and over (Nov 11)

Chuck kept getting Blue Velvet as a wildcard after rating it, and Cutter's Way as every veto replacement.
There were two causes, so there are two fixes:
1. Only tallied sessions counted as "recent". Now any film offered in a kickoff, follow-up or replacement
   isn't offered again for 36 hours (state.shown). A follow-up may keep the picks it narrows, and a narrow
   ask that fits nothing else falls back to films already offered rather than coming up empty.
2. New ratings only reached the taste profile at 5 AM. Now movie_night.seen reads the household's diary
   RSS and the first page of films sorted by rating date, at most every 15 minutes, and drops anything
   just watched or rated, except the open session's picks. (Nov 11: the rated-date page returns 403 to Delo, so only the RSS is read, and a rating with no diary entry waits for 5 AM.)

## Wildcards come only from the circle (Nov 11)

A wildcard used to be either a film TMDB recommends from one the household loved, or one the circle
scored highly. The TMDB recommendations were filler: they kept surfacing the same well-known titles. Now a
wildcard is an unseen film that someone the household follows loved, which means they gave it 4 stars or
more, hearted it, or wrote a clearly warm review (negative words outrank the stars). Wildcards rank by how
many of those people loved it, with diminishing returns: one fan is worth about 6.7 of 17, two 10.7,
three 13.2, five 15.6. The household's taste fit only breaks ties (20%), and the quality score blends in as
for every pick. Shorts under an hour are left out. A film with one fan also needs 50 TMDB votes, unless it
came out this year or last. TMDB lookups are capped at 300 new films a day and cached, so the pool grows
over the first few days. Many of the circle's favorites are festival films that aren't out yet, so the
pool of 30 is filled walking down the list and keeping only films that stream on a household service or
can be rented (up to 200 availability checks a run).

A count from the circle's feeds on Nov 11 (stars and hearts only; the review sentiment lives on Railway):
264 people, 12,154 diary entries, 2,957 films the household hasn't seen that clear the bar. 2,301 have
one fan, 385 two, 116 three and 155 four or more. The top of the list is mostly 2026 releases.

## Cheaper review extraction (Nov 11)

The first full extraction ran out of the $20 API credit. Reading the circle's 5,862 reviews with Opus cost
more than the estimate, mostly in output. Extraction is simple reading, so it now uses Haiku with thinking
off, which costs about 1/40th as much; the whole backlog comes to roughly a dollar. Picks for nuanced asks
stay on Opus. Each sync reads at most 2,000 reviews, with 4★+ and hearted reviews first because they're
the ones quoted under picks. Progress is saved every 10 batches, so a run that stops partway keeps what
it already paid for.

## A private test chat (Nov 11)

Chuck wanted to try Delo alone, without texting the household group. Delo only watched MNA_CHAT_ID, so a
one-on-one text went unanswered. Setting MNA_TEST_CHAT_ID makes Delo watch a second chat too. It answers
there exactly as in the group, but its sessions, vetoes, history and recently offered films are kept in
data/test/, so testing never changes what the household is offered or who can veto.

## Ask Linq for iMessage on every send (Nov 11)

In Chuck's one-on-one test chat, Linq sent Delo's replies as SMS even though the chat itself was iMessage,
and none of them arrived. A message sent with preferred_service "iMessage" went out as iMessage and was
delivered, so every send now asks for it. Linq's SDK marks the field deprecated. If Linq drops it, this
needs another fix.

## New on streaming, coming soon, hidden gems and taste twins (Nov 11)

Chuck found that "3 from the watchlist + 2 wildcards" mostly exposed films they'd seen before they met and
never logged. He wanted less obvious picks. His standouts (Exotica, A Little Romance, Incendies, Burning,
Metropolitan, Red Rooms, Yi Yi) have 91 to 3,569 TMDB votes, against about 10,000 for Sicario and 22,000 for
Parasite. Their TMDB averages are unremarkable (6.6 to 8.1). So popularity is what we take from TMDB, and
quality comes from the blended score.

A plain kickoff now fills five picks in this order (picker.mix):
1. **New on your services 🆕** (up to 2): watchlist films that started streaming on a household service in
   the last 14 days. This is read from the daily availability snapshots, and a film counts only if an earlier
   snapshot shows it on the watchlist without that service, so it never guesses.
2. **A taste twin's pick 👯** (1): a film that someone who rates like you loved. If there's no such film, a
   plain circle wildcard goes last instead. A twin is someone in the circle whose stars agree with the
   household's on shared films: agreement over (shared films + 3), at least 0.45. On Nov 11 that was 32
   people. Twins also count extra when ranking every wildcard.
3. **Hidden gems 💎** (up to 2), from the watchlist or the circle: blended quality of 70 or more from at least
   two sources, with 50 to 4,000 TMDB votes.
4. The watchlist by taste fills the rest. At most two picks share a first genre.

**Coming soon:** the intro adds "📅 Coming to rent soon: …" for watchlist films and circle favorites whose US
digital release (from TMDB) falls in the next 14 days. There's no free source for "arriving on Netflix next
week", so the digital date is the honest signal.

**Other changes:**
- Wildcards older than two years with more than 4,000 TMDB votes are skipped, since you've likely seen them
  without logging them.
- Circle agreement saturates more slowly: one fan is worth about 3.8 of 17, two 6.7, four 10.7 and eight 14.7.
- The sync stores each film's TMDB vote count and US digital date, and rechecks the date weekly while it's
  unknown or still ahead.

Deep cuts from directors you love are parked for later.

## 🙈 "seen it" (Nov 11)

A 🙈 on a pick means you've seen the film. Delo remembers it in data/seen-it.json, which every chat shares,
so the film is never offered again. It also takes the film out of tonight's picks, so medals on it no longer
count, and swaps in another film in the same spirit. This isn't a veto, so it doesn't use anyone's veto, and
the replacement can still be vetoed or 🙈'd. Delo can't write to Letterboxd, so its reply includes a
letterboxd.com/tmdb/<id> link for logging the film in one tap. Once it's logged, the taste profile learns
from it too.

## Wildcards need consensus (Nov 11)

Nosferatu the Vampyre (1979) came up as a wildcard because one person in the circle loved it. A wildcard now
needs at least two people who loved it (4★+, a heart, or a warm review), or one taste twin. On Nov 11's
feeds, that leaves about 650 films with two or more fans, plus the films a twin loved. Added Metrograph to the
circle.

## Festival prizes, Criterion, and what the circle loved (Nov 11)

Two cheap sources of richer signal:

**Honors from Wikidata** (movie_night/honors.py). Wikidata is open, keyed by TMDB id, and answers about
150 films per query. For each film Delo keeps:
- notable wins: Palme d'Or, Golden Lion and Golden Bear, other top festival prizes, and the major Oscars;
- the Criterion Collection spine number.

On Nov 11, 348 of 1,489 films had one or the other: 113 with a notable win and 268 Criterion releases.
Three of Chuck's standouts are Criterion (Yi Yi, Exotica and Metropolitan). Wikidata's coverage of festival
prizes is patchy (it misses Yi Yi's Cannes Best Director), so IMDb-Awards is the fallback if that matters.
Kometa's dataset is scraped from IMDb, which is why it isn't used first.

How honors are used:
- Picks show a "🏆 Golden Bear · Criterion Collection" line.
- Claude sees them for nuanced asks.
- They count toward hidden gems: a Criterion release or festival winner with few ratings is treated as
  quality 75.
- They're cached in data/honors.json and refreshed every 30 days.

**What the circle loved.** The review extraction already records up to three "loved" phrases per review.
Delo now totals them per film from people who liked it, most mentioned first. Picks show "❤️ Loved for: the
score, the ending" when there isn't a quote, and Claude sees the phrases too.

## Critics at the festival, from cannes-ratings (Nov 11)

Chuck found Reini Urban's cannes-ratings (cannes-ratings.org, data at github.com/rurban/cannes-ratings). Each
year it collects critics' scores from Cannes (since 2010), Sundance (2015), Berlinale (2016) and Venice (2025):
Screen Daily's jury grid, Le film français, ioncinema, critic.de, the ICS panel, Moiree and single reviews, all
converted to 0-10. For a new festival film, that's two dozen critics months before Rotten Tomatoes or
Metacritic say much.

movie_night/festivals.py fetches the data files from raw.githubusercontent.com (past years once, the last two
years weekly) into data/festivals.json, about 3,400 films. Per film it keeps:
- the critics' mean, leaving out the Letterboxd users the files also list and critics listed twice;
- where that put the film among the festival's rated films that year;
- the jury prizes from the main competition.

Films are matched to Delo's by English or original title, and by year within one. When both sides name a
director, the directors must share a name too. On Nov 11's data, 127 of 1,159 films matched.

How it's used:
- **Quality.** The festival rank is averaged into the critics part of the blended score, or becomes the critics
  part when there's no Rotten Tomatoes or Metacritic yet. A new festival film with a Letterboxd average then has
  two sources, so it can count as a hidden gem.
- **Picks.** Picks show "🎟️ Cannes 2025 critics: #8 of 93 (6.9/10)" when the film ranked in the top quarter.
  The line shows rank because festival means bunch up: Sentimental Value won the Grand Prix with a 6.5 mean.
- **Claude** sees the rank and mean for nuanced asks.
- **Honors.** Jury prizes fill in honors when Wikidata hasn't caught up on a recent festival yet.

## Quieter morning logs (Nov 13)

- Three watchlist films (Dekalog, Serial Experiments Lain, Caligula: The Ultimate Cut) and two circle-loved
  films point at TMDB ids that TMDB answers with 404. They used to be looked up again every morning. They're now
  marked `tmdb_missing` and rechecked once a month.
- Delo's log lines go to stdout. Railway marks everything on stderr as an error, so every line showed red.
- The taste line now counts taste twins and coming-soon films. The quality line counts films with festival
  critics.
