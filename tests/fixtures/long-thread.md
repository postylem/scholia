# Should We Use a Monad Transformer Stack?

Our Haskell service currently threads configuration, logging, and database access
through function parameters. The codebase has grown to the point where most functions
take five or six arguments, and adding a new cross-cutting concern means touching
dozens of signatures. A monad transformer stack (e.g., `ReaderT Config (LoggingT
(ExceptT AppError IO))`) would let us access these implicitly, but introduces its
own complexity.
