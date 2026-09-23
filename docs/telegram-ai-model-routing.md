# Telegram AI model routing

The listener uses the OpenAI Responses API for text and tool calls.

| Request | Default model | Reasoning |
| --- | --- | --- |
| Everyday messages, image analysis, memory writes | `gpt-6-luna` | low |
| Canonical memory promotion | `gpt-6-luna` | low |
| `/gpt`, `/chatgpt`, long-form scripts | `gpt-6-sol` | high |
| `/astra` (explicit escalation, including images and scripts) | `gpt-6-astra` | high |
| Video and YouTube analysis | `GEMINI_MODEL` | Provider default |

Configuration overrides: `CONFIO_AI_DAILY_MODEL`, `CONFIO_AI_IMAGE_MODEL`,
`CONFIO_AI_CANONICAL_PROMOTION_MODEL`, `OPENAI_MODEL`, and
`CONFIO_AI_ESCALATION_MODEL`. Their reasoning settings are
`CONFIO_AI_DAILY_REASONING_EFFORT`, `CONFIO_AI_CANONICAL_PROMOTION_REASONING_EFFORT`,
`OPENAI_REASONING_EFFORT`, and `CONFIO_AI_ESCALATION_REASONING_EFFORT`.
Images use the daily effort unless an explicit OpenAI command selects another model.
`CONFIO_AI_AGENT_MODEL`, when set, overrides the daily tool-agent model.

Model selection does not grant additional memory-write permissions. Existing
sender authority and write-intent checks still apply. Gemini continues to handle
video inputs because these OpenAI models do not accept video directly.

After changing configuration, restart `telegram-ai-listener`. Verify the effective
settings and a Responses API request using the production key before rollout.
