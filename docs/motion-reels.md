# Motion Reels

`publish_format: motion_reel` builds each Reel from HTML/CSS/GSAP motion graphics
rendered by [HyperFrames](https://github.com/heygen-com/hyperframes) (headless
Chrome + FFmpeg). If the motion render fails for any reason the post falls back to
the plain `reel` format (a slideshow of the still images), so nothing is skipped.

- Needs Node 22+, FFmpeg, `npm ci` at the repository root (pins `hyperframes` in
  `package.json`), and once `npx hyperframes browser ensure` (Chrome Headless Shell).
  `HYPERFRAMES_BIN` overrides the CLI location.
- `python -m narovva.motion out.mp4` renders a sample Reel covering every scene.
- Templates live in `src/narovva/motion/templates/reel/`. GSAP, the Lucide icons and
  the Archivo Black / Inter / JetBrains Mono fonts are vendored, so renders need no CDN.
- Everything on screen is a pure function of timeline time (no clocks, no unseeded
  randomness), because HyperFrames renders by seeking to frames in any order.

## The explainer storyboard

By default (`motion.story.mode: storyboard`) one LLM call
(`narovva.motion.storyboard`) writes an explainer for video from the brief and the
article text, as 5–14 beats: hook, context, what happened, fallout, verdict, call to
follow. Each beat is one or two spoken lines plus the scene that shows them,
picked from the library in `templates/reel/scenes.js`.

The writing rules come from studying high-performing explainer Reels frame by frame:

- **A hook that opens a loop** in at most 9 words: a contradiction with the named
  players, the stakes for the viewer, or a startling number.
- **One everyday analogy** for the mechanism ("your API is a nightclub; every request
  is a guest"), introduced once and reused in later lines.
- **The viewer cuts in.** Up to `motion.story.viewer_questions` beats (default 2) are
  the question the viewer would ask at that moment ("Wait, so who pays for this?"),
  read by a second voice and answered by the next beat. It makes the reel feel like a
  conversation rather than a lecture.
- **Receipts.** The key claim is shown once in the article's own words, on a paper
  card, with a marker sweeping over the key phrase.
- **Pace.** A new beat every 2–4 seconds, and the camera punches in a step on each
  new spoken line.

The scenes:

| scene | what moves |
|---|---|
| `headline` | the statement slams in; an icon draws itself on (the opener sits on the article photo) |
| `question` | "WHY?" letter by letter, a floating icon |
| `dates` | a date track whose focus moves to the next date with each spoken line |
| `chain` | nodes joined by links a pulse runs down; a broken link shows hazard tape |
| `grid` | tiles pop in with drawn icons; stamps (`BLOCKED`) hit the ones they apply to |
| `cards` | evidence cards, one per line, each with its own verdict stamp |
| `number` | one figure counts up (or from one figure to another) on an accent wash |
| `stats`, `compare` | rings, bars and the change between two figures |
| `split` | who wins and who pays |
| `quote` | the real quote on a card, its key words marked as they are said |
| `terminal` | facts typed out like a log |
| `checklist` | the verdict, then what to watch |
| `ask` | the viewer's question in a message bubble, typed in as the second voice says it |
| `source` | the receipt: the article's own sentence on a paper card over a dimmed background, the key phrase highlighted |
| `recap` | the short version as a table, the row being said lit |
| `world` | a 3D scene where characters and objects act the story out (below) |

### The story world

`world` scenes (`templates/reel/world.js`, three.js) are small 3D dioramas on the
reel's navy ground, seen from an isometric camera. Characters (with arms that swing,
cheer and slump) and objects are built from primitives in code, so there is nothing
to license, and every frame is a pure function of time. Line 1 of the beat sets the
scene up and line 2 is the turn. The writer picks a set piece and writes its labels
(which may use the analogy's words; any figure in them must be in the source):

| piece | what happens |
|---|---|
| `gate` | people queue at a door; a keeper lets the first few in, then a barrier drops and the rest are turned away |
| `flow` | money, goods, data, people, oil, chips or documents travel between two places; at the turn the flow grows, stops at a barrier or reverses |
| `pile` | a stock of items grows or drains, the figure before and after on it; a bystander cheers or slumps |
| `race` | two or three rivals run; the leader pulls away and crosses the line |
| `split` | one crowd divides onto a winners' and a losers' platform |
| `machine` | inputs ride a belt into a machine and come out as something else |
| `wall` | traffic crosses between two places, then a wall goes up and stops it |
| `balance` | two sides on a scale; it tips to the heavier one |

One WebGL context serves every world scene. Without WebGL a world scene shows its
title alone. Preview them all with
`python -m narovva.motion.preview out/ --story worlds`.
| `cta` | the end card: logo, handle, follow button |

The reply is checked before use: unknown scenes and malformed data are dropped,
every figure on screen must appear in the brief or the article, quotes and source
cards must be word for word (a source card from the article text itself), viewer
questions must be questions and never open or close the reel, and the Reel always
ends on the call to follow. If fewer than five beats
survive, the Reel falls back to `slides` mode (the carousel slides, re-animated).

## What is on screen

- **The article's own photo.** poster-core exposes the photo it sourced;
  `narovva.motion.photo` turns it into a sharp framed card on the opening scene and a
  blurred, darkened copy behind every scene. A tall, large photo goes full-bleed. A
  photo that is too small, banner-shaped or really a logo is skipped and the Reel
  runs on its generative background alone.
- **Charts from the story's numbers.** `narovva.motion.dataviz` parses the stated
  figures: a percentage becomes a ring that fills, figures that share a unit become
  bars on one scale, a comparison becomes two bars with the change between them.
  Only numbers the article states are drawn.
- **A background that never sits still.** A canvas field of light streaks in the
  category accent (`templates/reel/ambient.js`), seeded per story.
- **An investigative frame.** A header styled as a case file
  (`● REC  CASE FILE: STARLINK … 00:00:04:29`) or a breakdown
  (`● STARLINK BREAKDOWN … 24 OCT 2026`), dated evidence cards, and verdict stamps
  (`BLOCKED`, `FALSE`, `-20%`) only where the data backs one.

## Narration and captions

- `narration:` in the channel YAML adds a voice-over: `openai`, `gemini`,
  `elevenlabs` or `kokoro` (free, local), with `fallback_providers` tried in order. A
  voice not used in the last few posts is picked (`post_history.narration_voice`);
  `exclude_voices` removes voices from every provider's pool. If every provider
  fails, the Reel still posts with music only.
- Each scene is timed to its spoken lines, so elements arrive as they are mentioned;
  the music ducks under the voice (-14 LUFS master).
- With narration on, the spoken words are burned in as captions (most people watch
  with the sound off). `motion.captions.style` picks `karaoke` (a few words at a
  time, the spoken one lit), `pill` or `brighten`; `narration.captions: false` turns
  them off.
- Audition voices by ear: run **Actions → Audition narration voices**, or
  `python -m narovva.narration.demo openai out/`.
- Each Reel gets a designed cover (`narovva.video.cover`) kept inside the 4:5 band
  the profile grid shows, and background music from Jamendo matched to the story's
  tone; recently used tracks are avoided (`post_history.music_track_id`).

## Configuring the look

`motion:` in the channel YAML (schema `MotionStyleConfig`; every option is commented
in `config/channels/example-tech-ig.yaml`) sets:

- `story`: mode (`storyboard` | `slides`), `max_beats`, `target_seconds`, `flood`,
  `viewer_questions`
- `hud`: header style (`chapter`: the current chapter in a chip at the top over one
  dash per chapter; `case_file`, `breakdown`, `brand`, `none`), a custom `label`
  (`{subject}`, `{category}`, `{brand}`, `{date}`), timecode or date, the rec dot
- `progress`: where the progress line runs
- `captions`: style (`boxed`: a few words on a white box, the spoken word inverted;
  `karaoke`, `pill`, `brighten`), highlight colour, words per chunk
- `stamps`: on/off, how many per Reel, colours per tone
- `timeline` (`cards` | `spine`), `heading_marks`, `grid`, `show_handle`

A channel without a `motion:` block gets the case-file look.

## Working on the template without Node

`python -m narovva.motion.preview out/` screenshots frames of every scene from a
local Chrome and writes a contact sheet. Options: `--photo PATH|none`,
`--no-captions`, `--at 1.5,4`, `--via T` (checks a frame is identical when reached
out of order), `--hud`, `--captions-style`, `--timeline`, `--no-stamps`, and
`--story slides`.

## Fonts for covers and the fallback Reel

Set `brand.font_path_bold` / `brand.font_path_regular` to `.ttf` files (DejaVu Sans
is bundled in `assets/fonts/`), so covers and fallback Reels look the same on every
machine instead of depending on installed system fonts.
