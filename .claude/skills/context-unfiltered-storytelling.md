# Context Unfiltered — Storytelling Philosophy & Thematic Graphics Guide

## The Core Idea

Every reel should **decode the problem behind the news**, not just report what happened. The viewer should leave knowing:
- **What** happened (the event)
- **Why** it's happening (the structural driver)
- **Who wins / who loses** (the human impact)
- **What it costs** (concrete stakes)
- **The bigger picture** (the systemic frame)

This turns a news update into a story — something the viewer will remember, share, and come back for.

---

## Narrative Arc (8 scenes, pick what the story supports)

| # | Scene kind | Kicker | Purpose |
|---|---|---|---|
| 1 | `hook` | _(category)_ | Curiosity-first cold open — a question, tension, or number that demands the next swipe |
| 2 | `text` / `evidence` | WHAT HAPPENED | The event itself, in one clear idea |
| 3 | `why` | WHY IT'S HAPPENING | The root cause — the structural force, incentive, or failure driving this |
| 4 | `impact` | WHO WINS / WHO LOSES | Name the winners and losers; add the real cost in concrete terms |
| 5 | _data scenes_ | varies | Stats, comparison, timeline, money flow, quote — only what the story actually supports |
| 6 | `bigger_picture` | THE BIGGER PICTURE | Zoom out: what is this story really about beneath the headline? |
| 7 | `conclusion` | WHAT HAPPENS NEXT | What comes next; if the article supports it, what to watch for |
| 8 | `cta` | — | Story-tied payoff (not generic "daily breakdowns"), then the follow ask |

**Rule:** include only the scenes the article actually supports. Filler is worse than a short reel.

---

## Thematic Motion Graphics

When writing a story brief, set `motion_theme` to match the story's primary world:

| Category | When to use | `interface_type` | Graphic style |
|---|---|---|---|
| `ai_product` | ChatGPT, Claude, Gemini, Midjourney, etc. | `chat_ui` | Floating chat bubbles, typing cursor, glowing prompt box |
| `code_tool` | VS Code, GitHub, Cursor, Copilot, dev tools | `code_editor` | Syntax-highlighted code, terminal, diff view |
| `design_tool` | Figma, Adobe, Canva, Framer, etc. | `design_canvas` | Component frames, layers panel, canvas elements |
| `geopolitical` | War, sanctions, elections, diplomacy | `map` | Animated map, flag accents, borders |
| `finance` | Markets, funding rounds, crypto, central banks | `network_graph` | Price charts, node graphs, currency symbols |
| `science` | Research, climate, medicine, space | `lab` | Data plots, molecular graphics, instrument UIs |
| `policy` | Legislation, regulation, court cases | `document` | Document pages, gavel, official seals |
| `social` | Platforms, viral moments, creator economy | `none` | Clean typographic treatment |
| `generic` | Everything else | `none` | Clean typographic treatment |

### `accent_color_hint` examples
- OpenAI / ChatGPT → `#10A37F`
- VS Code / GitHub → `#007ACC` / `#24292E`
- Figma → `#F24E1E`
- Google / Gemini → `#4285F4`
- Meta → `#0866FF`
- Apple → `#555555`

---

## Writing Rules for the Analysis Prompt

When `understand.py` returns the brief, these fields drive storytelling quality:

**`root_cause`** — must answer "why is this happening?" at the structural level. Not "the company released a product" but "because regulators failed to act before the technology scaled". One sentence, grounded strictly in the article.

**`who_benefits` / `who_is_hurt`** — name specific actors (companies, groups, countries, demographics), not generic "consumers" or "the public". Keep it to the most direct winner and loser.

**`real_cost`** — quote a number or concrete consequence from the article: "$40 billion in market value erased", "12,000 jobs at risk", "2 degrees of warming by 2040". Null if the article provides nothing concrete.

**`bigger_picture`** — one sentence that names the systemic pattern: "This is part of a decade-long shift in how governments regulate AI" or "This follows a pattern of tech companies monetising safety research". The viewer should feel they understand something, not just that they saw news.

**`hook`** — the HOOK scene headline. Never the article title. Use: a striking number, a question that exposes tension, or a short statement that demands explanation. "Could your mind live forever?" beats "Scientists study brain data storage."

---

## The `scream` Scene

Use when the story has a single number so large, absurd, or precise that it deserves its own screen. The number takes up 80% of the frame; the label is tiny beneath it.

Good candidates: "$1 trillion market cap milestone", "67% accuracy drop", "Zero employees hired", "14 seconds to jailbreak".

Do not manufacture a scream number — only use it when the article explicitly states a value this striking.

---

## CTA Slide

The CTA is never generic. Its body should be the `bigger_picture` or `closing_line` — a line that makes the viewer feel they just learned something worth returning for.

❌ "Follow @contextunfiltered for daily breakdowns."  
✅ "Follow @contextunfiltered — the forces reshaping AI are moving faster than the news."

The heading stays as the follow ask; only the body line is story-specific.
