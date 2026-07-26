Here's what changes on the Auth Service (Django) side to make it Eureka-aware — conceptually, not code:

## 1. Add a Eureka client library
Django has no native Eureka support (that's a Java/Spring Cloud concept), so you need a third-party Python package that speaks Eureka's REST registration protocol. The standard choice is **`py_eureka_client`**. Add it to your Poetry dependencies just like any other package.

## 2. Decide what "the app" registers as
Eureka needs to know:
- **App name** (e.g. `auth-service`) — this is the ID other services will use to look it up.
- **Instance host/IP** — inside Docker Compose, this should be the container's service name (e.g. `auth-service`), not `localhost`, since other containers reach it over the Docker network by name.
- **Instance port** — whatever port Django/Gunicorn is actually listening on inside the container.

## 3. Add registration logic to app startup
The Eureka client needs to be initialized when the Django app boots — pointed at the Eureka Server's URL (its Docker service name + port 8761), with the app name/host/port from step 2. This is typically wired into Django's app startup hook (e.g. `AppConfig.ready()` or a startup script) so it fires once, when the WSGI/ASGI process comes up — not on every request.

## 4. Configure a health check endpoint
Eureka periodically wants a way to know the instance is actually healthy, not just "registered." You'll want a lightweight health endpoint (e.g. `/health/` or `/api/health/`) that returns 200 OK quickly — no DB writes, no heavy logic. This gets referenced in the Eureka client config as the health-check URL.

## 5. Handle heartbeats
The Eureka client library manages sending heartbeats automatically on an interval (matching Eureka Server's expected 30s renewal window) — you don't build this yourself, just make sure the client is running continuously as a background thread/process alongside Django, not something that starts and immediately exits.

## 6. Handle graceful deregistration
When the Django process shuts down (container stop, restart, deploy), the Eureka client should send an explicit deregister call rather than just letting the lease expire. This usually means hooking into a shutdown signal (SIGTERM) so Docker's normal container stop sequence triggers a clean deregistration instead of leaving a stale "zombie" entry for 90 seconds until Eureka's eviction timer clears it.

## 7. Update `.env` / config
Add new environment variables for:
- Eureka Server URL (Docker-internal, e.g. `http://eureka-server:8761/eureka/`)
- App name, instance host, instance port
This keeps the Eureka connection details out of hardcoded settings, consistent with how you're already managing secrets in `.env`.

## 8. Update `docker-compose.yml`
- Add a `depends_on: eureka-server` for the Auth Service so Compose at least *attempts* to start Eureka first (though remember NFR9 — your app should still retry-with-backoff if Eureka isn't fully ready yet, since `depends_on` only waits for container start, not app readiness).
- Confirm both containers are on the same Docker network so `auth-service` can resolve `eureka-server` by name.

## 9. Verify
Once wired up, restart both containers and check the Eureka dashboard at `localhost:8761` — you should see `AUTH-SERVICE` appear as a registered application with one `UP` instance. That's your confirmation this side is working before you move on to wiring Chat Service the same way.
