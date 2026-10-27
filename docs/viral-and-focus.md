# Viral posts and focus mode

## Viral posts

On top of the genre rotation, a channel with a `viral:` section posts the story the
internet is talking about right now, whatever its genre, in peak-hour slots
(`slots`, local times in `timezone`; at least one post per slot, and a missed slot
is made up in the next slot's window). `narovva run-due` checks the slots every
hour, before the rotation; a run that posts a viral story leaves the rotation post
for the next run.

- **Viral** = the same story carried by at least `min_sources` different outlets
  within `max_age_minutes` (about 30 big news feeds plus the channel's own genre
  feeds), with a bonus when it is also a hot Google Trends search (`trends_geos`).
  Google Trends alone never qualifies a story: most of its list is sports and
  celebrities.
- **Informative**: headlines matching `exclude_keywords` (scores, lotteries, gossip)
  are dropped, then an AI editor picks from the top `editor_candidates`, rejecting
  sports, gossip and stories with no wider consequence. If nothing qualifies, no
  post; the slot stays open.
- **Hook**: written from the analysed article's facts, `curiosity` (a question only
  the story answers) or `stakes` (what is at risk for the viewer). It opens the Reel
  on screen and in the voice-over, titles the cover under TRENDING NOW, and is the
  caption's first line.
- A story already posted (by either path, any outlet's link, or a similar headline
  in the last 48 hours) is never posted again.
- Preview: `narovva viral-scan <cfg> --editor`. Post one now: **Actions → Hourly
  publish → Run workflow**, tick `viral`.

## Focus mode

A channel's `focus:` section narrows everything it posts to one audience for as
long as `enabled: true`:

- the rotation posts from `focus.genres` instead of the channel's genres (the live
  channel uses `ai_practitioner`: OpenAI, Hugging Face, GitHub changelog, AWS ML,
  NVIDIA developer, Cursor, Simon Willison, Latent Space and the AI trade press;
  see `src/narovva/genres.py`);
- articles must be fresh (`max_age_hours`), mention one of `include_keywords` and
  none of `exclude_keywords`, then an AI screener ranks them by how useful they are
  to `audience` and drops the rest;
- viral posts must be on topic too, and the editor, hook, voice-over and caption
  (`caption_voice`, `extra_hashtags`) speak to that audience.

Set `enabled: false` to return to the normal genre mix; nothing else changes.

## Genres

`info-snipe` ships `ai`, `tech`, `world`, `business`, `science` and `gaming`;
narovva adds its own in `src/narovva/genres.py` (for example `entrepreneurs` and
`ai_practitioner`). A genre's `country` narrows its sources by region.

Scheduling: with `rotation_minutes` the channel posts at most one article every N
minutes, cycling through genres in the order listed; without it, each genre runs on
its own `cadence_minutes` clock.
