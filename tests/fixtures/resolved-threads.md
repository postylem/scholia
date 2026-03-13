# Error Handling in Distributed Systems

Distributed systems fail in ways that monolithic applications do not. Network
partitions, message reordering, clock skew, and partial failures create failure
modes that are difficult to reproduce and reason about. A robust error handling
strategy must account for all of these.

Retry policies are the first line of defense. Exponential backoff with jitter
prevents thundering-herd problems when a downstream service recovers. Circuit
breakers add a second layer by stopping requests entirely when a service is known
to be unhealthy, allowing it time to recover without being overwhelmed by retry
storms.

Idempotency is the foundation that makes retries safe. If an operation can be
applied multiple times without changing the result beyond the initial application,
then retrying is always safe. Achieving idempotency typically requires either
natural idempotency (reads, deletes by ID) or idempotency keys that allow the
server to deduplicate requests.
