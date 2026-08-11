# Design Review: Authentication

## Outcome
Approved with reservations.

## Team convention
All JWT tokens issued by Team Alpha services must have a maximum lifetime
of 15 minutes, with a separate refresh token lasting 8 hours.

## Risks
Key rotation is not yet automated.
