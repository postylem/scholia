# Versioning Strategies for APIs

When designing a public API, choosing a versioning strategy early prevents painful
migrations later. The three most common approaches are URI path versioning
(`/v1/users`), header-based versioning (`Accept: application/vnd.api+json;version=1`),
and query parameter versioning (`/users?version=1`).

URI path versioning is the most visible and debuggable approach. Developers can see
the version in browser address bars, curl commands, and logs without any special
tooling. Its main drawback is that it implies the entire API surface changes with
each version, even when most endpoints remain identical.
