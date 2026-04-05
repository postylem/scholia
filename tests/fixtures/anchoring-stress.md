---
title: Anchoring Stress Tests
author: Test
date: 2026-03-27
bibliography: references.bib
---

# first

arstarst

## second 

arstas

### third

t

#### fourth

arstas

##### fifth

arst

###### sixth?

## Identical Spans {#sec:identical}

These two subsections contain a block of identical text (>200 chars)
so the standard 32-char prefix/suffix window sees the same context
in both. Disambiguation requires widening beyond the duplicated block.

### Context Alpha

The Ising model originated in statistical mechanics as a simplified
model of ferromagnetism. Ernst Ising solved the one-dimensional case
in his 1924 doctoral thesis and found no phase transition.

The relationship between information entropy and optimal coding
demonstrates a fundamental limit in data compression. Shannon's source
coding theorem proves that no lossless compression scheme can compress
a message to fewer bits than its entropy, on average. This theoretical
bound guides the design of practical compression algorithms and
information-theoretic security proofs across many applied subfields
of mathematics and engineering.

The Huffman coding algorithm achieves optimality among prefix-free
codes, assigning shorter codewords to more probable symbols.

### Context Beta

The Potts model generalizes the Ising model to more than two spin
states. When the number of states $q$ exceeds four, the transition
on a square lattice becomes first-order rather than continuous.

The relationship between information entropy and optimal coding
demonstrates a fundamental limit in data compression. Shannon's source
coding theorem proves that no lossless compression scheme can compress
a message to fewer bits than its entropy, on average. This theoretical
bound guides the design of practical compression algorithms and
information-theoretic security proofs across many applied subfields
of mathematics and engineering.

Turbo codes and LDPC codes approach the Shannon limit within a
fraction of a decibel, enabling reliable deep-space communication.


## Math-Surrounded Words {#sec:mathwords}

The word "converges" appears near similar math in each subsection,
differing only in the trailing expression.

### Variant One

Under mild regularity conditions, $\sum_k a_k$ converges $\zeta(s)$
to a finite limit when the terms decrease monotonically.

### Variant Two

Under mild regularity conditions, $\sum_k a_k$ converges $\zeta(s)\zeta(2s)$
to a finite limit provided the Dirichlet series has abscissa $\sigma_c < 1$.

### Variant Three (different leading math)

Under mild regularity conditions, $\prod_k (1 - a_k)$ converges $\zeta(s)$
to a nonzero limit when $\sum_k a_k$ is finite.


## Cross-References {#sec:crossreftest}

As shown in @sec:identical, identical text spans require wide-context
disambiguation. The math-surrounded examples in @sec:mathwords show
that inline equations change the anchoring landscape. See the main
result in @eq:elbo below and the architecture in @fig:arch.


## Image Span

Consider the following diagram:

![Data flow from ingestion through transformation to
storage](images/pipeline.png){#fig:arch}

As illustrated in @fig:arch, the pipeline has three independent stages.


## Footnotes

The concept of entropy[^defn] was introduced in 1948 and remains
the cornerstone of information theory. A closely related quantity,
mutual information[^mi], measures statistical dependence between
two random variables and arises naturally in channel capacity proofs.

[^defn]: Entropy is defined as $H(X) = -\sum_{x} p(x) \log p(x)$.
    For a continuous distribution, the sum becomes an integral:
    $$H(X) = -\int_{-\infty}^{\infty} f(x) \log f(x)\, dx$$

[^mi]: Mutual information $I(X;Y) = H(X) - H(X|Y)$ quantifies
    how much knowing $Y$ reduces uncertainty about $X$. Equivalently,
    $$I(X;Y) = \sum_{x,y} p(x,y) \log \frac{p(x,y)}{p(x)\,p(y)}$$

## Citations

Shannon's foundational paper [@shannon1948] established the theoretical
limits of data compression and reliable communication over noisy channels.
Blah blah blah also we'll talk about some seminal work by @turing1936 on
computability.


## Display Equations {#sec:equations}

The evidence lower bound (ELBO) is central to variational inference.
For observed data $x$ and latent variables $z$, the objective is:

$$L_\phi = \mathbb{E}_{z \sim p}\left[\log \frac{p(z)}{q_\phi(z)}\right]$$ {#eq:elbo}

Minimizing @eq:elbo with respect to $\phi$ is equivalent to minimizing
the KL divergence $D_{\mathrm{KL}}(q_\phi \| p)$. The expectation in
@eq:elbo is taken under $p$, not $q_\phi$, which distinguishes this
from the standard ELBO formulation where the expectation is under
$q_\phi$.

The gradient of @eq:elbo can be estimated via Monte Carlo:

$$\nabla_\phi L_\phi \approx \frac{1}{N} \sum_{i=1}^{N} \nabla_\phi \log q_\phi(z_i)$$ {#eq:gradient}

Combining @eq:elbo and @eq:gradient yields a practical stochastic
optimization procedure.


## Repeated Characters in Math {#sec:repeated}

Dense expressions like $\sum_{i=1}^{n}x_i^2+ x_i + x_i x_j$ contain
many repeated single characters. The variable $x$ appears in $x_i$,
$x_j$, $x_i^2$, and the product $x_i x_j$. Adjacent math spans like this $xyz$&ZeroWidthSpace;$abc$ Selecting a single $x$
within any sub-expression is a degenerate case.

Similarly $\alpha + \alpha\beta + \alpha \beta\gamma$ repeats the symbol
$\alpha$ three times with progressively longer tails.
