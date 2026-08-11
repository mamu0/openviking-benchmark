# Postmortem: API Beta latency degradation

## Root cause
The degradation on March 12th was caused by an exhausted connection pool:
the HTTP client was instantiated inside the handler function instead of at
module level, creating a new pool on every invocation.

## Fix
Instantiate the client at module level with an explicit limit of 50
connections.
