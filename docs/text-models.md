# Text models

Each article costs several LLM calls (analysis, hook, storyboard, voice-over
script, caption). A single free-tier model runs out of daily quota after a few
articles and answers 503 when busy, so `llm_chain:` in the channel YAML lists models
in order, as `provider[:model]` with providers `claude-code`, `anthropic`, `gemini`, `openai` and `openrouter`:

```yaml
llm_chain:
  - claude-code:claude-sonnet-5-5
  - anthropic:claude-sonnet-5-5
  - gemini:gemini-flash-latest
  - gemini:gemini-3.5-flash-lite
  - openrouter:meta-llama/llama-3.3-70b-instruct:free
  - openai:gpt-4o-mini
```

- `claude-code:` is Claude on a claude.ai plan: `claude setup-token` prints a one-year token
  (store it as `CLAUDE_CODE_OAUTH_TOKEN`), and narovva runs the Claude Code CLI headless
  with no tools (`claude -p`). Only Claude Code accepts that token. It shares the plan's usage
  limit with your own Claude use; when the limit is hit, the next model answers for the run.
  The child process gets no `ANTHROPIC_API_KEY`, since Claude Code would prefer it to the token.
- `anthropic:` is Claude through the official SDK (`ANTHROPIC_API_KEY`, paid, billed to
  the Anthropic Console organization -- a claude.ai Pro subscription does not cover it).
  It goes first: a paid key has no daily quota, so the long storyboard and director calls
  get a strong model all day; the free models behind it are the fallback.
- A model whose quota is spent is skipped for the rest of the run; an overloaded one
  is retried with backoff; a short per-minute rate limit is waited out.
- Free-tier quotas are per model, so each Gemini model is a separate pool. OpenRouter
  `:free` models are a separate provider (`OPENROUTER_API_KEY`); entries without a
  key are skipped.
- A retired or misspelled model id (404) is skipped for the run.
- When no model is left, the run stops at once without counting failed attempts
  against the articles, so they are retried next time.

Free model names change often; edit the list, no code change needed.
