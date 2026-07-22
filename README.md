```python
import os
import zipfile

markdown_content = """# Auth-Service: The Official Integration Bible

This document serves as the comprehensive, definitive guide for integrating the **Auth-Service** into any distributed architecture. It outlines the step-by-step deployment process, external REST APIs (HTTP/JSON), internal gRPC contracts, and asynchronous event schemas.

---

## 1. Architectural Overview

The Auth-Service acts as the centralized Identity Provider (IdP) for the ecosystem. It is designed around a strict segregation of communication protocols:

*   **REST/HTTP (External):** Used exclusively by frontend applications (e.g., React SPA) for user registration, login, and token acquisition.
*   **gRPC (Internal):** Used by backend microservices for low-latency, high-throughput token validation and user data retrieval.
*   **Pub/Sub (Asynchronous):** Emits lifecycle events allowing decoupled services to react to state changes (e.g., triggering a profile creation workflow when a user registers).

---

## 2. Local Setup & Deployment

The service is fully containerized for a deterministic setup across environments.

**Step 1: Clone and Configure**
```bash
git clone <repository_url> auth-service
cd auth-service
cp .env.example .env

```

*(Ensure all database credentials and secret keys are populated in the `.env` file.)*

**Step 2: Build and Spin Up**

```bash
docker-compose up -d --build

```

This initializes the PostgreSQL database, the Django application (serving HTTP), and the gRPC server.

**Step 3: Initialize Database Schema**

```bash
docker-compose exec auth-service python manage.py migrate

```

---

## 3. REST API Reference (Frontend / Client Integration)

Frontend applications should communicate with the Auth-Service over HTTP using standard JSON payloads.

### 3.1. Authenticate (Login)

Exchanges user credentials for an access token and a refresh token.

* **Endpoint:** `POST /api/auth/login/`
* **Headers:** `Content-Type: application/json`

**Request Payload:**

```json
{
  "email": "developer@example.com",
  "password": "securepassword123"
}

```

**Success Response (200 OK):**

```json
{
  "status": "success",
  "data": {
    "user_id": "usr_9a8b7c6d5e",
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "refresh_token": "def5020059c99ec3...",
    "expires_in": 3600
  }
}

```

### 3.2. Register User

Registers a new identity in the system.

* **Endpoint:** `POST /api/auth/register/`
* **Headers:** `Content-Type: application/json`

**Request Payload:**

```json
{
  "email": "newuser@example.com",
  "password": "securepassword123",
  "first_name": "John",
  "last_name": "Doe"
}

```

**Success Response (201 Created):**

```json
{
  "status": "success",
  "data": {
    "user_id": "usr_1x2y3z4w5v",
    "email": "newuser@example.com"
  },
  "message": "User registered successfully."
}

```

---

## 4. gRPC Protocol Reference (Backend Microservice Integration)

For backend-to-backend communication (e.g., verifying a token when a request hits a resource server), utilize the gRPC interface to avoid HTTP overhead.

### 4.1. Protobuf Contract (`auth.proto`)

Client microservices must use this exact `.proto` definition to generate their local stubs.

```protobuf
syntax = "proto3";

package auth;

service AuthService {
  // Validates an access token and returns the user identity
  rpc VerifyToken (VerifyTokenRequest) returns (VerifyTokenResponse);
}

message VerifyTokenRequest {
  string access_token = 1;
}

message VerifyTokenResponse {
  bool is_valid = 1;
  string user_id = 2;
  string email = 3;
  repeated string roles = 4;
  string error_message = 5;
}

```

### 4.2. Step-by-Step Backend Integration Example

If you are building a downstream REST API—for example, a Job Tracking microservice (`job-service`) built with Spring Boot—here is how the gRPC call occurs when a request arrives.

**Step 1:** The frontend (React) includes the `access_token` in the HTTP `Authorization` header when requesting data from the `job-service`.
**Step 2:** The `job-service` intercepts the request, extracts the token, and makes a gRPC call to the Auth-Service.

**Spring Boot Implementation Example:**

```java
import auth.AuthServiceGrpc;
import auth.Auth.VerifyTokenRequest;
import auth.Auth.VerifyTokenResponse;
import net.devh.boot.grpc.client.inject.GrpcClient;
import org.springframework.stereotype.Service;

@Service
public class SecurityValidationService {

    // Injects the gRPC channel pointing to the Auth-Service cluster
    @GrpcClient("auth-service-channel")
    private AuthServiceGrpc.AuthServiceBlockingStub authStub;

    public UserPrincipal validateRequest(String jwtToken) {
        VerifyTokenRequest request = VerifyTokenRequest.newBuilder()
            .setAccessToken(jwtToken)
            .build();
            
        VerifyTokenResponse response = authStub.verifyToken(request);
        
        if (!response.getIsValid()) {
            throw new UnauthorizedException("Invalid or expired token: " + response.getErrorMessage());
        }
        
        return new UserPrincipal(
            response.getUserId(), 
            response.getEmail(), 
            response.getRolesList()
        );
    }
}

```

---

## 5. Event-Driven Architecture (Pub/Sub Schemas)

To maintain a decoupled architecture, the Auth-Service publishes domain events to the message broker. Downstream services should subscribe to these topics to synchronize their local state.

### 5.1. Topic: `auth.events.user_created`

Triggered immediately after a successful registration.

**Event Payload (JSON):**

```json
{
  "event_id": "evt_459823749823",
  "timestamp": "2026-07-22T11:28:00Z",
  "type": "USER_CREATED",
  "payload": {
    "user_id": "usr_1x2y3z4w5v",
    "email": "newuser@example.com",
    "first_name": "John",
    "last_name": "Doe"
  }
}

```

*Use Case:* A notification service listens to this topic to send a welcome email, or a billing service listens to create a free-tier subscription record.

### 5.2. Topic: `auth.events.token_revoked`

Triggered when a user logs out globally or when an administrator flags an account.

**Event Payload (JSON):**

```json
{
  "event_id": "evt_998347598347",
  "timestamp": "2026-07-22T11:45:00Z",
  "type": "TOKEN_REVOKED",
  "payload": {
    "user_id": "usr_9a8b7c6d5e",
    "reason": "MANUAL_LOGOUT",
    "revoked_at": "2026-07-22T11:45:00Z"
  }
}

```

*Use Case:* API Gateways or downstream services listen to this to aggressively clear localized caches of valid sessions.
"""

os.makedirs('output', exist_ok=True)
md_path = 'output/auth-api-bible.md'

with open(md_path, 'w', encoding='utf-8') as f:
f.write(markdown_content)

zip_path = 'auth-api-bible.zip'
with zipfile.ZipFile(zip_path, 'w') as zipf:
zipf.write(md_path, arcname='auth-api-bible.md')

print(f"File generated: {zip_path}")

```

```text?code_stdout&code_event_index=1
File generated: auth-api-bible.zip


```

Your Markdown documentation file is ready


I have created an exhaustive, professional integration guide for your API. It clearly defines the system boundaries and breaks down the exact payloads needed for every step of the authentication flow.

Here is what is included in the `.md` file:

* **System Overview:** A clear distinction between when to use HTTP, gRPC, and Pub/Sub.
* **REST Definitions:** The exact JSON payloads for the login and registration endpoints.
* **gRPC Contract:** The `auth.proto` definition showing exactly how a downstream microservice asks the `auth-service` to verify a token.
* **Integration Example:** A complete Java implementation showing how a separate backend (like a `job-service`) intercepts a frontend request and uses a gRPC stub to validate the token.
* **Pub/Sub Schemas:** The JSON event structures emitted by the system so that your decoupled services can safely listen and react to user creation or token revocation events.
