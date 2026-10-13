# Auth Service API

Django authentication and authorization service for the chat application.

The service exposes a REST API on port `8000` and a gRPC API on port `50051`.

## Service URLs

| Interface | Local URL |
| --- | --- |
| REST | `http://localhost:8000` |
| gRPC | `localhost:50051` |

## REST API

All REST request bodies must be JSON. The REST API does not use a version prefix
for service probes; application endpoints are grouped under `/api/v1/auth/`.

### Service probes

| Method | Endpoint | Authentication | Description |
| --- | --- | --- | --- |
| `GET` | `/health/` | None | Returns the service health status. |
| `GET` | `/info/` | None | Returns the service name and description. |

Example health response:

```json
{
  "status": "ok"
}
```

### Authentication endpoints

| Method | Endpoint | Authentication | Description |
| --- | --- | --- | --- |
| `POST` | `/api/v1/auth/login/` | None | Authenticates a user and returns an access token and refresh token. |
| `POST` | `/api/v1/auth/refresh/` | None | Rotates a refresh token and returns a new token pair. |
| `POST` | `/api/v1/auth/logout/` | Refresh token or access token | Revokes the supplied refresh token and/or access token. |
| `POST` | `/api/v1/auth/validate/` | Access token | Validates an access token and returns its claims. |
| `GET` | `/api/v1/auth/permissions/` | `Authorization: Bearer <access_token>` | Returns the current user's roles and permissions. |

#### Login

Request:

```http
POST /api/v1/auth/login/
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "your-password"
}
```

Successful response (`200`):

```json
{
  "access_token": "<jwt>",
  "access_jwt": "<jwt>",
  "token_type": "Bearer",
  "expires_in": 900,
  "refresh_token": "<opaque-refresh-token>",
  "refresh_expires_at": "2026-09-12T10:00:00+00:00"
}
```

Possible errors: `400` for missing or invalid JSON fields, `401` for invalid
credentials, and `429` when the login rate limit is exceeded.

#### Refresh token

Request:

```json
{
  "refresh_token": "<opaque-refresh-token>"
}
```

The refresh token is single-use. A successful response has the same token-pair
shape as login. Invalid, expired, or previously used refresh tokens return `401`.

#### Logout

The request must contain at least one token. Tokens may be supplied in the JSON
body, and the access token may alternatively be supplied as a bearer header.

```http
POST /api/v1/auth/logout/
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "refresh_token": "<opaque-refresh-token>"
}
```

Successful response: `204 No Content`.

#### Validate access token

The access token can be supplied in the JSON body or as a bearer header.

```http
POST /api/v1/auth/validate/
Authorization: Bearer <access_token>
Content-Type: application/json

{}
```

Successful response (`200`):

```json
{
  "active": true,
  "claims": {
    "sub": "<user-id>",
    "email": "user@example.com",
    "roles": ["member"],
    "permissions": ["chat.read"],
    "token_type": "access"
  }
}
```

Invalid tokens return `401` with `active: false`.

#### Get permissions

Request:

```http
GET /api/v1/auth/permissions/
Authorization: Bearer <access_token>
```

Successful response (`200`):

```json
{
  "user_id": "<user-id>",
  "roles": ["member"],
  "permissions": ["chat.read"]
}
```

Missing or invalid bearer tokens return `401`.

### Administration endpoint

| Method | Endpoint | Authentication | Description |
| --- | --- | --- | --- |
| `POST` | `/api/v1/auth/admin/users/<user_id>/ban/` | Admin bearer token | Bans a user and revokes their active refresh and access sessions. |

Request body:

```json
{
  "reason": "user_banned"
}
```

`reason` is optional and defaults to `user_banned`. The caller must have the
required authorization permission. The endpoint returns `403` when the caller
is authenticated but not authorized, `404` when the target user does not exist,
and `401` for an invalid or missing bearer token.

Successful response (`200`):

```json
{
  "detail": "User banned.",
  "user_id": "<user-id>",
  "revoked_refresh_tokens": 1,
  "revoked_access_sessions": 1,
  "revocation_published": true
}
```

### Django admin

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/admin/` | Django admin interface. |

This is a browser-based administration interface, not part of the versioned
JSON API.

## gRPC API

The gRPC service is defined in [`proto/auth.proto`](proto/auth.proto).

- Service: `auth.AuthService`
- Address: `localhost:50051`
- Transport: gRPC over HTTP/2
- Authentication: the caller passes the access token in `TokenRequest.access_token`.

### `ValidateToken`

```protobuf
rpc ValidateToken(TokenRequest) returns (TokenValidationResponse);
```

Request:

```protobuf
message TokenRequest {
  string access_token = 1;
}
```

Response:

```protobuf
message TokenValidationResponse {
  bool active = 1;
  string user_id = 2;
  repeated string roles = 3;
  repeated string permissions = 4;
}
```

For a valid token, `active` is `true` and the user identity, roles, and
permissions are returned. For an invalid token, the service returns
`active: false`.

### `GetPermissions`

```protobuf
rpc GetPermissions(TokenRequest) returns (PermissionsResponse);
```

Response:

```protobuf
message PermissionsResponse {
  string user_id = 1;
  repeated string roles = 2;
  repeated string permissions = 3;
}
```

This method validates the supplied access token and returns the user's roles and
permissions. Token validation failures are returned as a gRPC error.

## Running locally

```bash
python3 manage.py migrate
python3 manage.py runserver 0.0.0.0:8000
python3 manage.py grpcrunserver --max-workers=10 0.0.0.0:50051
```

With Docker Compose, both ports are exposed automatically:

```bash
docker compose up --build
```