Testing some markdown things to see that they render well:

First some math:


Here are some examples of math in different markdown formats:

**Inline math (dollar signs):**  
$D_{\mathrm{KL}}(P \,\|\, Q) = \sum_{x} P(x) \log \frac{P(x)}{Q(x)}$

$\LaTeX$

**Display math (double dollar signs):**  

$$\LaTeX$$

**Inline math (escaped parens):**  

\(\LaTeX\)

**Display math (escaped brackets):**  

\[\LaTeX\]



**Python code example:**

```python
def greet(name):
    print(f"Hello, {name}!")

greet("World")
```

**LaTeX code example:**

```latex
\documentclass{article}
\begin{document}
Hello, \LaTeX!
\end{document}
```




# Heading One

Any text with no empty lines between will become a paragraph.
Leave an empty line between headings and paragraphs.

Font can be *Italic* or **Bold**.
Code can be highlighted with `backticks`.
Hyperlinks look like [GitHub Help](https://help.github.com/).
You can add footnotes.[^1]

[^1]: example footnote definition.

## Heading Two

Images look similar:

![alt text here](https://upload.wikimedia.org/wikipedia/commons/4/4b/Focus_ubt.jpeg)

### Heading Three

A bullet list is created using `-`, `*`, or `+` like:

- dog
- cat
- muffin

A numbered list is created using a number + `.` + space, like:

1. one
2. two
6. three
2. four

A complicated list:

1. dog
    - bark
    - wag
2. cat
    - meow
6. muffin
    - yum

> Block quote.
> Continuing the quote.

Horizontal rule:

-------

## Table Test

| column1 | column2 | column3 |
| --- | --- | --- |
| value | value | value |
| value | value | value |
