# NutriBase

FastAPI-based food image nutrition estimation service.

## Setup

1. Install Python dependencies: `pip install -r requirements.txt`.
2. Copy `.env.example` to `.env` and replace the placeholder API key.
3. Start the backend: `python -m uvicorn main:app --host 127.0.0.1 --port 8001`.
4. Browse `http://127.0.0.1:8001/docs` for API documentation.

## API

- `POST /analyze` accepts multipart fields **file** (JPG/PNG image) and **weight_g** (positive number), and returns the nutrition report.
- `GET /reports` returns the JSON-backed report history.
- `GET /openapi.json` gives the machine-readable API schema.

Example: `curl -X POST http://127.0.0.1:8001/analyze -F 'file=@meal.jpg' -F 'weight_g=350'`

## Browser / Cloudflare tunnel integration

Cloudflare quick tunnel URLs are ephemeral. Use the current active HTTPS URL, verify `/openapi.json`, and configure the frontend against **/reports**, not **/records**. The backend has no CORS middleware at present, so browser requests from a separate origin may be blocked. This needs to be configured for allowed frontend origins before browser-based integration will work.

See [CODEX_TASK.md](CODEX_TASK.md) for developer instructions. Do not commit real secrets or local report history.
