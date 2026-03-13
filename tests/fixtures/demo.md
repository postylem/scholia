---
title: Notes on Software Design
author: V
date: 2026-03-12
---

# The Lindy Effect

The Lindy effect is a theorized phenomenon by which the future life expectancy of
some non-perishable things, like a technology or an idea, is proportional to their
current age. Under this framework, every additional period of survival implies a
longer remaining life expectancy.

The concept is named after Lindy's delicatessen in New York City, where comedians
would gather and observe that the amount of material a comic had was the best
predictor of how long their career would last. Nassim Nicholas Taleb later
formalized the idea in *Antifragile*, arguing that books that have been in print
for a hundred years are likely to remain in print for another hundred.

One practical implication is in technology selection. If a programming language has
survived for forty years, it is more robust than one released last year — not
because age is inherently good, but because survival is evidence of fitness. This
is why Unix, SQL, and Lisp keep reappearing despite periodic declarations of their
obsolescence.

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

# Numerical Computing

Einstein's mass-energy equivalence $E = mc^2$ is perhaps the most famous equation
in physics, but in computational terms it is trivially simple. The real challenges
emerge when we discretize continuous mathematics for machine execution.

The forward difference approximation computes the derivative as:

$$
f'(x) \approx \frac{f(x + h) - f(x)}{h}
$$

A naive Python implementation reveals the floating-point pitfalls:

```python
def forward_diff(f, x, h=1e-8):
    """Compute f'(x) using forward difference."""
    return (f(x + h) - f(x)) / h

# Catastrophic cancellation for small h
import math
result = forward_diff(math.sin, 1.0, h=1e-15)
# Expected: cos(1) ≈ 0.5403
# Actual: 0.0 (total cancellation)
```

The error in the central difference method scales as $O(h^2)$, compared to $O(h)$
for the forward difference.
