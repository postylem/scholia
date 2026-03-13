---
title: "Notes on Information Theory"
author: V
date: 2026-03-12
bibliography: references.bib
---

# Notes on Information Theory

Shannon's foundational paper [@shannon1948] introduced the concept of
*information entropy*, a measure of the uncertainty in a random variable. The
entropy of a discrete random variable $X$ with possible values $\{x_1, \ldots,
x_n\}$ is defined as:

$$
H(X) = -\sum_{i=1}^{n} p(x_i) \log_2 p(x_i)
$$

This quantity has a beautiful interpretation: it is the minimum average number of
bits needed to encode messages from the source.^[This is the *source coding
theorem*, also from Shannon's 1948 paper. The proof is non-constructive ---
Huffman coding came later as a practical algorithm.]

## Channel Capacity

A communication channel has a maximum rate at which information can be
transmitted reliably, called the *channel capacity*:

$$
C = \max_{p(x)} I(X; Y)
$$

where $I(X; Y) = H(X) - H(X \mid Y)$ is the mutual information. For a binary
symmetric channel with crossover probability $\epsilon$:

$$
C = 1 - H(\epsilon) = 1 + \epsilon \log_2 \epsilon + (1 - \epsilon) \log_2 (1 - \epsilon)
$$

The noisy channel coding theorem [@shannon1948] tells us that for rates below
capacity, there exist codes that achieve arbitrarily low error probability.

## Connections to Computer Science

Knuth discusses the relationship between information theory and algorithm
analysis in depth [@knuth1997, ch. 2]. The entropy of a distribution over
inputs gives a lower bound on the expected number of comparisons needed by any
comparison-based sorting algorithm:

$$
\log_2(n!) \approx n \log_2 n - n \log_2 e
$$

This is why $\Theta(n \log n)$ is the best we can do for comparison sorts.

Turing's original model of computation [@turing1936] can be viewed through an
information-theoretic lens: a Turing machine is essentially a channel that
transforms input tapes to output tapes, and the halting problem is a statement
about the limits of compression.

## Entropy in Practice

Here is a simple Python function to compute the Shannon entropy of a
distribution:

```python
import math

def entropy(probs):
    """Compute Shannon entropy in bits."""
    return -sum(p * math.log2(p) for p in probs if p > 0)

# Fair coin: maximum entropy for 2 outcomes
print(entropy([0.5, 0.5]))  # 1.0 bit

# Biased coin
print(entropy([0.9, 0.1]))  # ≈ 0.469 bits

# Fair die
print(entropy([1/6] * 6))   # ≈ 2.585 bits
```

And an equivalent in Haskell:

```haskell
entropy :: [Double] -> Double
entropy = negate . sum . map (\p -> if p > 0 then p * logBase 2 p else 0)
```

## References
