# Hooks and performance metrics

## Hooks, packaging and voice

Every post (with `hooks.enabled`; viral posts always) opens on a formula hook:

- **Formulas**: `src/narovva/hooks/formulas.yaml` holds 18 hook shapes (The Mistake,
  The Warning, The Comparison, The Deadline, ...) adapted from
  [youtube-agent-skill](https://github.com/Jakeschincariol/youtube-agent-skill) (MIT).
  `hooks.formulas` picks the ones a channel uses.
- **One call, several options**: the model writes `hooks.candidates` packages, each a
  hook from a different formula plus a 2–4 word **cover** title and the caption's
  **opener**.
- **Rules in code**: a hook is rejected if it restates the headline, answers itself,
  uses a number the article does not contain, or a banned word. The cover must not
  share the hook's words; the opener fits the 125 characters shown before "more".
- **Score**: `src/narovva/hooks/score.py` rates each hook 0–100 on specific / talks to
  you / stakes / open question / length (60% mean, 40% weakest); below
  `hooks.min_score` is rejected. It is a heuristic that filters summaries and hype;
  it does not predict views. Each post records `hook_text`, `hook_formula`,
  `hook_score` and `cover_text` in `post_history`.
- **Voice**: the `voice:` block (audience, banned words, claims we never make,
  format) goes to every writer; banned words are also stripped from the caption.

## Performance report

The **Performance metrics** workflow runs daily (and on demand):

1. `narovva collect-metrics` snapshots each post from the last 14 days through
   Instagram's insights API (views, reach, likes, comments, saves, shares, average
   and total watch time) into `post_metrics`, one row per post per day.
2. `narovva performance-report` judges every post by its **multiple**: its views 48 h
   after posting divided by the median of the channel's previous 30 posts (raw views
   mostly track follower growth). It lists the top and bottom posts, the average
   multiple per hook formula and per topic (once a group has 5 posts), average watch
   time, and one recommendation. The report is on the workflow run's summary page.
3. With `hooks.learn: true` the hook writer leans on formulas that beat the median:
   once a formula has 20 measured posts, a proven-weak one (under 0.85x) is left out
   and proven-strong ones come first; 20% of posts still get every formula.

Reading insights needs the token's `instagram_business_manage_insights`
permission: check with **Actions → Instagram insights probe**.
