# PRD: Checkout Service v2

## Context
The checkout service handles payments for the citizen portal.

## Architectural decision
We adopt a Saga pattern with centralized orchestration to manage
distributed transactions. The choreographed pattern was discarded because
it makes state reconstruction opaque in case of partial failure.

## Requirements
- Idempotency on all payment calls via an Idempotency-Key.
- Maximum end-to-end timeout of 8 seconds.
