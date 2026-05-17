"""
Discord REST rate-limit and retry strategy (skeleton — Phase 2).

Design (from docs/discord_integration_boundary.md §12):
- Exponential backoff with jitter on 429 Too Many Requests.
- Respect the retry_after header exactly.
- Global rate-limit sentinel: back off globally on a global 429.
- Non-critical bulk messages (e.g. reminder DMs): 1–2 s delay between sends.
- Critical ephemeral responses: use InteractionResponse.defer() +
  followup.send() for use cases taking > 1 s.
- Retry budget: max 3 attempts per outbound message; on exhaustion, write
  a discord_dispatch_failures row (status='failed').

No Discord SDK imported until Phase 2.
"""
