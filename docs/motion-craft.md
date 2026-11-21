# Story-first motion: the method and its quality gates

How narovva turns an article into a Reel when `story.mode: story_first`. The story decides the pictures, never the
other way round. Every step is checked before the next one runs; a failed check goes back to the step that can fix it.

## The pipeline

| Step | Who | What it produces | Gate (narovva.motion.quality) | On failure |
|---|---|---|---|---|
| 1. Write | the writer chain (Claude Opus 5.5 first) | complete beats: lines, captions, facts, what to SEE, a ≤5-word takeaway (setup / turn) per beat, the story's hero object | **story_review**: coverage of who/what/when/why/numbers/impact/next; a hook beat with a first line ≤9 words (fails above 12); event and impact beats; a verdict before the call to action; 20–170 s | the writer is asked once more, with the gaps named |
| 2. Direct | the writer chain | a picture per beat: an info scene, or a `compose` scene of the story's own actors animated on its lines | **direction_review**: ≤20% headline-only beats, ≤30% pictures failing validation, at least half the beats with different pictures, at least 40% animating what happens (moves, grows, blocks, counts); the hero recurring | the director is asked once more, with the reviewer's notes; failed pictures take the local director's (no model call), then the beat's takeaway as a headline |
| 3. Lay out | headless Chrome on the staged page | every scene measured at its settled moment | **layout_audit** (motion/render.py): no text clipped out of the scene window, no text on text, nothing under 22 px | the failing scene becomes its takeaway headline (same voice, same timing); measured again |
| 4. Render | HyperFrames | the MP4 | duration matches; **loudness_review**: about −14 LUFS, true peak ≤ −0.5 dBTP | logged in the reel's quality line |

The run log carries one line per reel, for example `reel quality -- story pass; direction pass; layout pass; loudness pass`.

## The craft (what the director is told, and what the renderer does)

The principles were distilled from studied reference reels (product reels, a cutout history explainer, a minimal brand
reel, a tutorial's AI-made explainers). They're principles only: no layouts, brands or characters are copied.

1. **One world in many states.** A beat about the same subject as the beat before keeps its actors (same labels). The
   renderer keeps them on stage and glides them to their new places; only what changed moves.
2. **Re-arrange the story's own objects** (group, sort, set against each other, connect, count) instead of decorating.
3. **Name things in place.** An actor appears on the word that names it (the caption clock), labelled on itself.
4. **Time is an object.** "When" beats are `dates` scenes with the real dates.
5. **Mood lives in the background.** The wash behind the scenes changes only when the story's part changes: context
   (blue), evidence (teal), impact (wine), reaction (violet), next (green), verdict (amber).
6. **The screen says the point.** Each beat's on-screen line is its takeaway: a setup and a turn, at most 5 words, with
   the turn highlighted. Not the spoken sentence.
7. **Animate the verb.** Moves, grows, shrinks, splits, joins, blocks, arrives, not an icon standing for it.
8. **One hero object** at the centre of the story, in the hook, back in the middle, resolved at the verdict.
9. **One idea per frame,** at most 5 actors, nothing on screen the voice doesn't say.

## Models

- `writer.chain` (channel YAML) writes and directs: `claude-code:claude-opus-5-5` (a claude.ai plan's token), then
  `anthropic:claude-opus-5-5` (an API key), then `llm_chain`. Everything else (analysis, hooks, captions) uses
  `llm_chain`, with Sonnet first.
- Without any model the story can't be written and the reel falls back to the slide-based one. Without a director the
  local director pictures the story from the writer's facts.

## Trying it

```
python -m narovva.motion.preview out/ --story story_first --hud case_file
```
