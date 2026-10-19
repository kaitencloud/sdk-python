# AI credit wrappers

The server prices every call. The SDK sends only model, request type and usage;
no prompts, responses or vendor prices are sent to Kaiten.

## Provider clients

Install `kaitencloud[openai]` (OpenAI 3.x, >=3.35.1) or
`kaitencloud[anthropic]` (Anthropic 1.x, >=1.15.0).

```python
from kaitencloud.openai import OpenAI

provider = OpenAI(
    api_key="your-provider-key", kaiten=kaiten, instance="acme-prod", pool="chat-credits"
)
reply = provider.chat.completions.create(model="your-model", messages=messages)
```

`AsyncOpenAI`, `Anthropic` and `AsyncAnthropic` use the same keyword options.
Provider and Kaiten clients must both be sync or both be async. An existing
client can be delegated with `wrap_openai(client, kaiten=..., instance=..., pool=...)`
or `wrap_anthropic(...)`. The wrapper does not own a supplied client's lifetime;
`close()` and context-manager exit delegate to that client. Copies made with
`copy()` / `with_options()` retain the meter.

Every metered call requires an explicit model. `estimator=` receives an
`AiRequest` and returns an optional usage estimate; by default serialized prompt
bytes/4 and the declared output ceiling (otherwise 1024 for completions) are
reserved. Reservation TTL follows the request/client timeout when available.

### Bounded surface

OpenAI: `chat.completions.create`, `responses.create`, `embeddings.create`,
`images.generate`, `audio.transcriptions.create`, `audio.speech.create`.
Anthropic: `messages.create`, `messages.stream`.

Unlisted methods/resources stay provider-owned, including raw/streaming HTTP
response helpers, parsing helpers, batches, realtime and tool runners. They are
not metered: use generic `kaitencloud.ai.run` when you need explicit accounting.

A refused reserve raises its typed error before the provider is called. An
unsupported server is logged once per meter and subsequent calls pass through
unreported. Settlement is best effort under the original transaction ID; a
failed commit is logged, never substituted for the provider result.

### Streams

Consume streams fully or close them explicitly; context managers are strongly
recommended. A bare `break` on a retained stream does not close it. Garbage
collection cannot reliably perform asynchronous settlement.

Chat streaming merges `stream_options.include_usage=True`. Responses uses the
terminal response usage without adding chat-only parameters. Anthropic starts
with `message_start` usage and overwrites cumulative fields from `message_delta`
(never sums these snapshots). Its `messages.stream()` context-manager factory,
`text_stream`, `until_done` and final-message helpers are preserved.

Settlement occurs once on completion, iteration failure or close. An abandoned
stream with received events reports `CUSTOMER_ERROR` and known usage; a stream
closed before receiving anything reports `NOT_SENT`, following the V1 wrapper
policy. Network/protocol failures report `PROVIDER_ERROR` unless the failure is
proven to precede sending. Image partial frames are not additional images;
completed images and actual returned image count supply units. Speech binary
responses and transcription text formats may expose no usage; these settle
without usage and the server applies its minimum/warning policy. Never infer
billable duration from compressed audio bytes.

Compatibility tests use actual optional SDKs and in-process mock transports,
never provider endpoints or credentials.

## Agent SDK constraints (survey 2026-10-19)

Do not mistake tool hooks or user-facing runs for model-inference boundaries.
No fake agent wrapper is shipped until it can satisfy the per-model-turn gate.

* Claude Agent (`claude-agent-sdk` 0.2.168, Python >=3.10):
  `AssistantMessage` exposes `model`, `usage`, `message_id` and subagent context;
  partial `StreamEvent` exposes raw Anthropic events. `ResultMessage` usage is
  aggregate. Public `HookEvent` includes tool/user/stop/subagent hooks but no
  before-every-model-call hook. A `PreToolUse` callback runs after inference.
  [Types](https://github.com/anthropics/claude-agent-sdk-python/blob/main/src/claude_agent_sdk/types.py).
* Codex (`openai-codex` 0.163.0, Python >=3.10): `Thread.run` / `turn` and sync/async
  handles are available. `thread/tokenUsage/updated` carries `thread_id`,
  `turn_id`, `token_usage.last` and `total`, but no model field. One user-facing
  turn may include multiple model calls. No awaited per-model-call veto hook is
  established by the public API.
  [API](https://github.com/openai/codex/blob/main/sdk/python/docs/api-reference.md),
  [usage types](https://github.com/openai/codex/blob/main/sdk/python/src/openai_codex/generated/v2_all.py).
* Copilot (`github-copilot-sdk` 1.0.22, Python >=3.11): `AssistantUsageData` exposes
  model, input/output/cache/reasoning counts; turn events and `agent_id` support
  attribution. `session.on(callback)` is synchronous; dispatcher exceptions are
  logged and do not stop inference. Session hooks expose no awaited per-model
  gate. Cache inclusion semantics need verification before normalizing usage.
  Runtime startup may auto-download binaries, so compatibility tests must not
  start real sessions.
  [Events](https://github.com/github/copilot-sdk/blob/main/python/copilot/generated/session_events.py),
  [callbacks/hooks](https://github.com/github/copilot-sdk/blob/main/python/copilot/session.py).

Post-call accounting adapters are possible, but cannot honestly promise the
required preflight for each internal model turn or subagent. Integration needs
a supported veto-capable model boundary or an explicitly approved scope change;
run-level budgets, private monkeypatches and hosted proxies are not substitutes.
