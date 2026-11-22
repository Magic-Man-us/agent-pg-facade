# Security policy

## Reporting a vulnerability

Report vulnerabilities privately through the repository's **Security** tab: **Report a vulnerability**. Do not open a public issue.

Include the affected version or commit, the configuration needed to reproduce it (capability flags, transport, whether keys are configured), and the smallest request that shows the problem.

## Supported versions

Fixes land on `main`. No older version receives fixes.

## Scope

In scope:

- Reaching data or operations that the configured PostgreSQL role, capability flags, or read-only mode should prevent.
- Authentication or authorization bypass on the REST API or MCP over HTTP.
- Credential or private data disclosure in responses, errors, or logs.

Out of scope:

- Anything the configured database user is already allowed to do. PGFacade enforces PostgreSQL privileges; it does not add row-level policy of its own.
- A caller holding the raw SQL capability switching to another role the connector belongs to. The [README](README.md#permissions) states this.
- A local stdio session acting as the database user in `PGFACADE_DSN`. That is the documented behavior of a keyless local session.

The trust boundaries and enforced controls of the reference deployment are in the [deployment security record](deploy/SECURITY.md).
