# PULSE — Journey API & JSON Error Repair Specification (`docs/JOURNEY_API_JSON_REPAIR.md`)

## 1. Problem Diagnosis
In early iterations, requests to `/api/v1/journeys` could fail under edge conditions (e.g. searching for a landmark not directly present in GTFS stop names or when backend routing threw an unhandled exception). Because FastAPI default exception handling returns plain-text or HTML (`"Internal Server Error"` or `{"detail": ...}`), frontend calls calling `res.json()` failed with the syntax error:
```
SyntaxError: Unexpected token 'I', "Internal Server Error" is not valid JSON
```

## 2. Architectural Remedy

### 2.1 Standardized Backend Error Contract
Every endpoint error (HTTP 4xx and 5xx) is intercepted and serialized through structured JSON response handlers adhering to the uniform schema:

```json
{
  "error": {
    "code": "INTERNAL_SERVER_ERROR" | "HTTP_ERROR" | "VALIDATION_ERROR" | "NO_STOPS_FOUND",
    "message": "Human-readable explanation of error condition",
    "status_code": 404,
    "request_id": "err_1795354000123",
    "details": {}
  }
}
```

### 2.2 Global Exception Interceptors (`app/main.py`)
Three global exception handlers guarantee that no raw HTML or plain-text response ever leaves the server:
- `@app.exception_handler(StarletteHTTPException)`: Intercepts all raised `HTTPException` instances, preserving status codes and extracting detailed messages into structured JSON.
- `@app.exception_handler(RequestValidationError)`: Intercepts query parameter and body validation errors, returning HTTP 422 with a structured field-level diagnostic.
- `@app.exception_handler(Exception)`: Catches all unexpected internal runtime errors, logs the full stack trace to the server log with unique `request_id`, and returns a safe HTTP 500 JSON payload.

### 2.3 Safe Client JSON Parser & AbortController (`frontend/static/js/app.js`)
All client-side API requests use the `safeFetchJson(url, options)` utility:
- Checks `res.ok` before attempting JSON decoding.
- Inspects the `Content-Type` header to ensure JSON MIME type.
- Extracts `errData.error.message` or `errData.detail` and displays user-friendly in-panel notices instead of browser alerts.
- Binds an `AbortController` to journey planning requests: if a user types or submits a subsequent query while one is in-flight, the preceding request is aborted immediately, discarding outdated responses and preventing race conditions.

### 2.4 Journey Response Contract with Unique IDs
The successful response contract enforces:
- `request_id`: Unique timestamped request identifier (`req_<epoch_ms>`).
- `query`: Echo of query inputs (`origin`, `destination`, `departure_time`, `date`).
- `options[].journey_id`: Globally unique identifier (`j_<request_id>_<option_id>`).
- `options[].legs`: Array of transit and walking legs containing explicit coordinate arrays (`geometry`), boarding/alighting coordinates, and predicted travel times.
