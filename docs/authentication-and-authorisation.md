# Authentication and authorisation boundary

This service is the IAM authority.  It stores passwords, verifies login
credentials, rate-limits repeated login attempts, records login history, and
issues credentials.  It does not decide whether a user may access a particular
message, conversation, or other domain resource.

## RBAC source of truth

Application RBAC uses only the IAM-owned `Role`, `Permission`, `UserRole`, and
`RolePermission` models. Django `Group`, Django `Permission`, and the
`User.groups` / `User.user_permissions` relationships are deliberately not
present on the custom user model and must not be used for application access.

Set `LOGIN_MAX_ATTEMPTS` and `LOGIN_ATTEMPT_WINDOW_SECONDS` for the login
throttle. Configure Django with a shared production cache so the limit covers
all IAM instances.

## Token contract

`POST /api/v1/auth/login/` accepts `email` and `password`, then returns a
short-lived JWT access token and an opaque refresh token.  `POST
/api/v1/auth/refresh/` rotates the refresh token, making the previous one
unusable.  `POST /api/v1/auth/logout/` revokes a refresh token.

Every access JWT contains these relevant claims:

| Claim | Meaning |
| --- | --- |
| `sub` | Immutable IAM user UUID. |
| `email` | Authenticated email address. |
| `roles` | Role snapshot at token issuance. |
| `permissions` | Permission snapshot derived from those roles. |
| `iss`, `aud`, `exp`, `nbf`, `jti` | Required issuer, recipient, lifetime, and token identity checks. |
| `token_type` | Always `access`; refresh credentials are never JWT access tokens. |

## What downstream services do

Each downstream service validates the JWT locally before it handles a request:

1. Verify its signature, allowed algorithm, `iss`, `aud`, `exp`, `nbf`, and
   `token_type == "access"`.
2. Use `sub`, roles, and permissions as trusted authenticated context.
3. Make its own resource-level decision.  For example, the messaging service
   checks both `messages.send` and whether the user is a participant in the
   target conversation.

No request-time call to this service is needed for that decision.  Access
tokens are intentionally short lived, so role changes take effect when a new
token is issued.

## Production key handling

The current `HS256` configuration is suitable only when every verifier is
trusted with the shared signing secret.  For independently deployed
microservices, use an asymmetric signing configuration (such as `RS256`): keep
the private key exclusively in this IAM service and distribute only the public
verification key, ideally through a cached JWKS endpoint.  Do not expose the
refresh-token database or password hashes to downstream services.
