# Public Web Deployment

This project can be deployed as one public web service: React static files,
Nginx, FastAPI, the background worker, SQLite, and PDF storage all run from one
Docker image.

## Recommended long-term deployment

For a public link that can be shared long term without Render payment setup, use
the VPS Docker guide:

```text
docs/deployment/VPS_DOCKER_DEPLOYMENT.md
```

That path builds and runs the Docker service on your own server. The final link
is either:

```text
http://SERVER_IP/
https://your-domain.example/
```

## One-click Render deployment

Use this link:

```text
https://dashboard.render.com/blueprint/new?repo=https://github.com/cjx528/ScholarMind
```

Render reads `render.yaml`, builds the root `Dockerfile`, attaches a persistent
disk at `/app/data`, and exposes one HTTPS URL such as:

```text
https://scholarmind.onrender.com
```

After Render reports the service as live, share the Render app URL and the site
password. Users do not need to clone the repository or install dependencies.

## Required deploy inputs

Fill these Render environment variables during Blueprint setup:

```text
AUTH_PASSWORD       site password users enter on the login page
ZHIPU_API_KEY       LLM key for generation
EMBEDDING_API_KEY   embedding key, usually the same Zhipu account
OPENALEX_EMAIL      optional but recommended for OpenAlex requests
```

`AUTH_SECRET_KEY` is generated automatically by Render. Leave optional provider
keys empty unless that provider is selected in settings.

## Local production smoke test

If Docker is available locally:

```powershell
docker build -t scholarmind-web .
docker run --rm -p 8080:8080 `
  -e AUTH_PASSWORD=demo `
  -e ZHIPU_API_KEY=your_key `
  -e EMBEDDING_API_KEY=your_key `
  scholarmind-web
```

Then open:

```text
http://127.0.0.1:8080
http://127.0.0.1:8080/health
```

## Architecture

Public request flow:

```text
Browser -> Nginx :${PORT}
Nginx /          -> React SPA
Nginx /api/*     -> FastAPI on 127.0.0.1:8000
FastAPI/worker   -> SQLite + PDFs under /app/data
```

Render notes:

- The public HTTP server must bind to Render's `PORT`; the startup script
  renders `infra/nginx.web.conf.template` with that value.
- The persistent disk keeps `scholarmind.db` and downloaded PDFs across deploys.
- Free web services can sleep after inactivity; use a paid instance for demos
  where cold starts are unacceptable.
