# Image to DXF — MCP server for laser-cutting artwork

This repository contains the client's Python converter and the HTTP MCP server that exposes it to ChatGPT-compatible MCP clients.

## What it does

- Converts PNG/raster artwork into DXF outline geometry.
- Converts SVG paths into DXF.
- Scales output to a requested width in millimetres.
- Writes raster external contours to the `OUTER` layer and holes/interior contours to `INNER`.
- Writes SVG paths to the `PATHS` layer.
- Exposes the `image_to_dxf` tool through a Streamable HTTP-style MCP endpoint at `/mcp`.
- Includes OAuth 2.1 Authorization Code + PKCE and dynamic client registration endpoints.

## Important architecture note

GitHub is the public source-code repository. It does **not** run this Python API or provide a permanent MCP endpoint. The MCP server must be deployed to a Python-capable HTTPS host. The live MCP URL is only known after deployment; it must not be guessed or replaced with the GitHub repository URL.

The included `render.yaml` is a Render Blueprint for deploying this repository as a Docker web service with a persistent disk. The Blueprint uses a paid Starter service plan and a persistent disk; review Render's current pricing before deploying.

## Deploy with Render

1. Open Render and choose **New → Blueprint**.
2. Connect the GitHub account that owns this repository.
3. Select `Arcane3D/Arcane3D` and deploy the Blueprint from `render.yaml`.
4. Review the service and persistent-disk charges before confirming.
5. Confirm the assigned service domain matches the `BASE_URL` configured in `render.yaml`. If Render assigns a different domain, update `BASE_URL` in the Render environment to the exact HTTPS origin.
6. Ensure `SECRET_KEY` is generated and retained by the hosting provider. Do not publish it.
7. Keep the persistent disk mounted at `/var/data`; the SQLite database and generated files are stored there.
8. Visit the service root URL. It should return JSON identifying the service and its `/mcp` endpoint.

## Connect to ChatGPT

After deployment, use the real HTTPS endpoint:

`https://YOUR-DEPLOYED-HOST/mcp`

In ChatGPT, enable Developer mode where available, add a custom MCP server/connector using that exact URL, choose OAuth when prompted, and complete the account sign-up or login page served by this application. Use only the OAuth redirect URIs shown in the ChatGPT connection flow; update `ALLOWED_REDIRECTS` in the hosting environment if ChatGPT displays an additional callback URI.

This repository URL is **not** the MCP endpoint. Do not enter `https://github.com/Arcane3D/Arcane3D` as the server URL.

## Run locally

Requires Python 3.11+ and the dependencies in `requirements.txt`.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export BASE_URL="http://localhost:8787"
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export DB_PATH="data/app.db"
export FILES_DIR="data/files"

uvicorn server:app --host 0.0.0.0 --port 8787
```

The OAuth callback flow requires an exact registered redirect URI. For a local test, configure `ALLOWED_REDIRECTS` to the exact callback URI supplied by the MCP client.

## MCP tool

Tool name: `image_to_dxf`

Arguments:

- `image`: attached file metadata containing `download_url`, `file_id`, and optional `mime_type` / `file_name`.
- `width_mm`: finished drawing width (1–5000 mm; default 100).
- `threshold`: raster threshold (0 selects automatically; 1–254 sets it explicitly).
- `invert`: trace light artwork on a dark background.
- `tolerance_mm`: outline simplification tolerance (default 0.1 mm).

## Known limitations from the supplied implementation

- The converter traces outlines and silhouettes; it does not create centerlines for engraving.
- Photographs generally do not produce clean laser-cut geometry without preprocessing.
- SVG text should be converted to paths before uploading.
- Input download size is limited to 15 MB; raster images are limited to 40 megapixels.
- The DXF download link expires after one hour.
- The supplied authentication implementation is a starter implementation: it does not include email verification, password reset, or shared rate limiting. Review and harden authentication, request validation, and file-fetch protections before opening the service to untrusted public traffic.
- DXF geometry should be reviewed in the machine's target software. The service does not validate kerf, material, focus, power, speed, or machine-specific requirements.

## Project files

- `server.py` — FastAPI application, OAuth endpoints, MCP tool, image tracing, DXF generation, and short-lived output downloads.
- `requirements.txt` — Python packages.
- `Dockerfile` — container image for the web service.
- `render.yaml` — Render deployment blueprint.
- `skills/image-to-dxf/SKILL.md` — ChatGPT tool-use guidance.
- `.env.example` — environment variable reference.
