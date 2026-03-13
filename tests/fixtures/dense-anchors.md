# The Architecture of a Compiler

A compiler transforms source code written in a high-level programming language into
machine code or an intermediate representation that can be executed by a target
platform. The classical pipeline divides this process into lexical analysis, parsing,
semantic analysis, optimization, and code generation. Each phase consumes the output
of the previous one, though modern compilers often blur these boundaries for
performance reasons. The lexer breaks the input stream into tokens, the parser
assembles tokens into an abstract syntax tree, semantic analysis checks types and
resolves names, the optimizer rewrites the tree or intermediate representation for
efficiency, and the code generator emits the final target code. Understanding this
pipeline is essential for anyone working on language tooling, IDE support, or
performance-critical systems.
