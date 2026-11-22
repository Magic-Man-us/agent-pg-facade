# Error contracts

[application/errors.py](../src/pgfacade/application/errors.py) owns exception mapping.
[contracts/envelopes.py](../src/pgfacade/contracts/envelopes.py) owns validation and serialization.
Python, HTTP, and MCP return the same operation error as `ResponseEnvelope(kind=..., outcome=Failure(...))`.
HTTP/MCP failures before dispatch use standalone `Failure(status="error", error=...)`.

Classification produces one trusted, frozen, slotted dataclass. SQLSTATE classification chooses
status, category, and reason together; it does not reconstruct database meaning from an HTTP
status. One renderer creates the public Pydantic `ApiError`/`Failure` output. HTTP uses that
same payload's status so an exception is classified once per response. Internal classification records do
not run Pydantic validation; the public schema and diagnostic payloads retain their serializers.

Raw Python request validation can raise `ValidationError`; transport adapters convert it at ingress.

| Error field | Meaning |
| --- | --- |
| `code` | Broad category from `ErrorCode`, such as `unauthenticated` or `unavailable` |
| `reason` | Specific machine-readable `ErrorReason`, such as `credential_missing` |
| `message` | Safe caller-facing explanation; clients must not parse it for classification |
| `status` | HTTP-equivalent error status, also carried by Python and MCP results |
| `sqlstate` | PostgreSQL SQLSTATE when available; otherwise `null` |
| `details` | Optional tagged diagnostic contract; otherwise `null` |

[ErrorCode, ErrorReason, and diagnostic enums](../src/pgfacade/contracts/enums.py) use `StrEnum`.
Raise specific application exceptions, such as `MissingCredential`, `NoMatchingPolicy`, or
`IdentityProviderInvalidResponse`, instead of inferring a reason from exception text.

| Status | Representative reasons |
| --- | --- |
| 400 | `request_invalid`: an invalid application request |
| 401 | `credential_missing`, `credential_invalid`: absent or rejected caller credentials |
| 403 | `policy_denied`, `policy_no_match`, `identity_ambiguous`: authorization failed |
| 422 | `input_invalid`: request validation failed |
| 500 | `response_invalid`: an internal result violated its contract; `unexpected_failure`: an unclassified fault |
| 502 | `identity_provider_invalid_response`: the provider returned a malformed identity |
| 503 | `authentication_unconfigured`, `identity_provider_unconfigured`, `identity_provider_unavailable` |

Only 401 adds the HTTP `WWW-Authenticate: Bearer` challenge. Provider configuration and availability
faults do not mean the caller supplied invalid credentials. Recognized provider `TimeoutError` and
`ConnectionError` failures become 503; an unknown provider exception remains a generic 500.

`details.kind` selects a discriminated Pydantic union with explicit enum tags:

- `authentication` and `authorization` carry the same `reason` as the top-level error.
- `database` carries optional `sqlstate` and a controlled category: conflict, constraint,
  not_found, permission, timeout, unavailable, or failure. Status and reason follow the SQLSTATE mapping.
- `validation` carries `origin` (`request` or `response`) and `issues`.

Each validation issue contains `path`, `code`, a generated `message`, and optional tagged `context`.
`context.kind="bounds"` contains declared numeric constraints as `bounds` entries with `name` and `value`.
`context.kind="tag"` contains an optional `discriminator` and the available `expected_tags`.
Messages abbreviate long choice lists; structured context retains the full list. A missing tag may
have no expected choices because the upstream validator did not supply them.

Validation issue codes remain an open string contract: `KnownValidationCode` names recognized
upstream codes but does not reject new ones. Clients must tolerate unknown issue codes and absent context.

Raise application exceptions only with safe caller-facing messages. Never interpolate credentials,
rejected values, SQL, server paths, or raw provider/database diagnostics into public messages.
Validation projection strips rejected inputs and arbitrary validator context; database errors expose
SQLSTATE and category without raw diagnostics. Unknown exceptions return `Internal server error`.

`error_payload()` logs every failure with status 500 or above to the `pgfacade` logger at `ERROR`
with its traceback. Caller failures below 500 are not logged.

Catch errors at validation/transport boundaries. Preserve cancellation: do not turn
`asyncio.CancelledError` into a failure envelope or catch `BaseException` to continue execution.

[Transport parity tests](../tests/integration/test_error_boundaries.py),
[structured-error tests](../tests/unit/test_structured_errors.py), and
[authentication tests](../tests/unit/test_authentication_error_reasons.py) cover classification,
Python/HTTP/MCP agreement, schema/JSON round trips, validation context, and private-value exclusion.
