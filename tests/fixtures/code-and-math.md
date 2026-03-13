---
title: Numerical Computing Patterns
author: V
date: 2026-03-12
---

# Numerical Computing Patterns

Einstein's mass-energy equivalence $E = mc^2$ is perhaps the most famous equation
in physics, but in computational terms it is trivially simple. The real challenges
emerge when we discretize continuous mathematics for machine execution.

## Numerical Differentiation

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

The central difference method is more numerically stable:

$$
f'(x) \approx \frac{f(x + h) - f(x - h)}{2h}
$$

## Type-Safe Numerical Code

Haskell's type system can encode physical dimensions at the type level,
preventing unit errors at compile time:

```haskell
{-# LANGUAGE DataKinds, GADTs, KindSignatures #-}

data Unit = Meters | Seconds | MetersPerSecond

data Quantity (u :: Unit) where
  Distance :: Double -> Quantity 'Meters
  Time     :: Double -> Quantity 'Seconds
  Velocity :: Double -> Quantity 'MetersPerSecond

divide :: Quantity 'Meters -> Quantity 'Seconds -> Quantity 'MetersPerSecond
divide (Distance d) (Time t) = Velocity (d / t)
```

## Browser-Side Computation

For interactive visualizations, JavaScript handles the rendering loop:

```javascript
function plotDerivative(canvas, f, fPrime, xMin, xMax) {
  const ctx = canvas.getContext('2d');
  const steps = canvas.width;
  const dx = (xMax - xMin) / steps;

  ctx.beginPath();
  for (let i = 0; i < steps; i++) {
    const x = xMin + i * dx;
    const y = fPrime(x);
    const px = i;
    const py = canvas.height / 2 - y * 50;
    i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py);
  }
  ctx.stroke();
}
```

The error in the central difference method scales as $O(h^2)$, compared to $O(h)$
for the forward difference. When $h$ is chosen optimally as
$h^* = \sqrt{\epsilon_{\text{mach}}}$, where $\epsilon_{\text{mach}} \approx 2.2 \times 10^{-16}$
for double precision, the central difference achieves roughly 8 digits of accuracy.
