# Text models

Each article costs several LLM calls (analysis, hook, storyboard, voice-over
script, caption). A single free-tier model runs out of daily quota after a few
articles and answers 503 when busy, so `llm_chain:` in the channel YAML lists models
in order, as `provider[:model]` with providers `gemini`, `openai` and `openrouter`:

```yaml
llm_chain:
  - gemini:gemini-flash-latest
  - gemini:gemini-3.5-flash-lite
  - openrouter:meta-llama/llama-3.3-70b-instruct:free
  - openai:gpt-4o-mini
```

- A model whose quota is spent is skipped for the rest of the run; an overloaded one
  is retried with backoff; a short per-minute rate limit is waited out.
- Free-tier quotas are per model, so each Gemini model is a separate pool. OpenRouter
  `:free` models are a separate provider (`OPENROUTER_API_KEY`); entries without a
  key are skipped.
- A retired or misspelled model id (404) is skipped for the run.
- When no model is left, the run stops at once without counting failed attempts
  against the articles, so they are retried next time.

Free model names change often; edit the list, no code change needed.
