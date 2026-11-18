# Content language (English and Hindi)

One setting switches the language of the content:

```yaml
# config/channels/<channel>.yaml
language: hi        # "en" (default) or "hi"
```

| | English (`en`) | Hindi (`hi`) |
|---|---|---|
| **Voice-over** | English | spoken Hindi, written in Devanagari |
| **On-screen text** (transcript, graphics, labels, cover) | English | **English**, the same story as the voice says it |
| **Caption** | English | **Hinglish**: Hindi in Roman letters mixed with English terms |
| **Hashtags** | English | English |
| **Voices** | the provider's English voices | Kokoro's Hindi voices (`hf_alpha`, `hf_beta`, `hm_omega`, `hm_psi`); OpenAI's and Gemini's voices are multilingual |

Articles are still read in English. Only what the viewer hears and the caption change.

## Switching

- **Always:** `language: hi` at the top of the channel config. Nothing else changes.
- **One genre only:** `language: hi` on a genre (`genres: - genre: ai ... language: hi`). A genre's setting beats the channel's.
- **One manual run:** Actions → "Hourly publish" → Run workflow → `language` (use it with `genre` or `viral`), or
  `narovva run-channel <cfg> --genre ai --language hi` / `narovva run-viral <cfg> --force --language hi`. A run's
  language beats the genre's and the channel's.

## Setup for Hindi

```yaml
narration:
  provider: openai
  fallback_providers: [gemini, kokoro]     # kokoro: free, local, needs no key, has Hindi voices
  # How the voice says the channel name. A Hindi voice garbles Latin names, so give the Devanagari spelling.
  spoken_names:
    hi: "कॉन्टेक्स्ट अनफिल्टर्ड"
  # Optional: the Hindi voices to rotate through (else the defaults above).
  voices_by_language:
    hi: [hf_alpha, hm_omega]
```

If `spoken_names.hi` is missing the run logs a warning and the voice reads the name in Latin letters.

## How it works

- **The story writer** (storyboard, or the slide script when the storyboard is off) is told to write each spoken
  line in natural, conversational Hindi and, for the same line, an **English caption** for the screen. Everything
  else on screen (scene data, titles, labels, stamps, quotes) stays English as before.
- **English terms in Hindi lines are written in Devanagari** (`एआई`, `मॉडल`, `डेवलपर`): a Hindi voice garbles
  Latin words (measured: "AI model" came out as "इनई आई मदल"). A glossary of common terms
  (`narovva/language.py`) swaps any that slip through in Latin letters.
- **Numbers** are digits exactly as the source writes them, with the unit in Devanagari (`67 प्रतिशत`,
  `120 मिलियन डॉलर`; never lakh or crore, so the "every figure must be in the source" check still holds). The voice
  reads digits in Hindi.
- **Checks run on the English text**: figures are grounded, "lecture" jargon and grim subjects are detected on the
  English caption. A Hindi line is dropped if it has no usable English caption, is not in Devanagari, or states a
  figure the source lacks. Devanagari never reaches the screen (the reel's fonts are Latin).
- **The call to follow** is fixed text in each language, with the spoken channel name.
- **The hook** is written once as English (on screen, on the cover, scored) plus a Hindi spoken version; the caption's
  first line is a Hinglish opener. Without a valid Hindi version the storyboard writer says the hook in Hindi itself.
- **The caption** is written in Hinglish by the caption writer; banned words and hashtags work as before.
- Each post records its language (`post_history.language`), and the performance report adds a "By language"
  section once both languages have posted.

## Voice quality

Kokoro's Hindi is a small local model: clear and brisk, but less expressive than OpenAI or Gemini. The checks that
guard it: numbers and English terms are spelled so it reads them correctly, and the free voices run at normal speed
(Hindi is already quick). If you have OpenAI or Gemini credit, set it as `provider` and Kokoro stays the fallback.

## Adding a language

Add a profile in `narovva/language.py` (the writers' rules, the checks, the call to follow, a glossary), its voices in
`narovva/narration/voices.py` and the espeak code for Kokoro. Everything else asks the profile.
