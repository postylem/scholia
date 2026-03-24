---
title: Scholia Demo
subtitle: A showcase of rendered markdown with margin annotations
author: Your Name Here
bibliography: references.bib
macros: macros.sty
---

## What is this?

Take notes in the margins of live-rendered rich text documents, and collaborate in comment threads with any AI assistant.

[Scholia](https://en.wikipedia.org/wiki/Scholia) were annotations added to manuscripts by medieval or ancient scholars for explanation, clarification and commentary. This is a tool for maintaining such marginalia on (markdown) text documents, and optionally using them to collaborate with an AI as the documents evolve.

![Scholia screenshot](demo_screenshot.png)

## Math

Pandoc renders LaTeX math via KaTeX. Inline math like $e^{i\pi} + 1 = 0$ works, as do display equations:

$$
H(X) = -\sum_{x \in \mathcal{X}} p(x) \log p(x)
$$

Shannon [-@shannon1948] showed that entropy gives a fundamental limit on lossless compression. The cross-entropy between distributions $p$ and $q$ is:

$$
H(p, q) = -\sum_{x} p(x) \log q(x) = H(p) + \KL{p}{q}
$$

where $\KL{p}{q}$ is the Kullback–Leibler divergence and $\E{p}{f(X)}$ denotes expectation under $p$. These macros are defined in an external `macros.sty` file referenced in the YAML frontmatter.

## Code

Syntax-highlighted code blocks:

```python
def entropy(p):
    """Shannon entropy in nats."""
    return -sum(pi * log(pi) for pi in p if pi > 0)
```

## Citations

Pandoc handles BibTeX citations automatically. For example: @turing1936 introduced the notion of computability, @knuth1997 wrote the definitive reference on algorithms, and @lamport1978 formalized event ordering in distributed systems.

Footnotes also work[^1], and can be rendered as sidenotes using the toggle in the Options menu.

[^1]: This is a footnote. Toggle "Footnotes" in the Options menu to see it rendered as a sidenote in the margin.

## References
