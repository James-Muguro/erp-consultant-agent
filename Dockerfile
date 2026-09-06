# syntax=docker/dockerfile:1

# ---- Stage 1: build the frontend ----
FROM node:22-slim AS frontend-build
WORKDIR /app/frontend

# Copy only the manifest files first so this layer is cached unless
# dependencies actually change - avoids a full npm ci on every build
# when only source files changed.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# Now copy the rest of the frontend source and build it.
COPY frontend/ ./
RUN npm run build


# ---- Stage 2: Python backend, serving the built frontend ----
FROM python:3.12-slim AS backend

WORKDIR /app

# System deps some Python packages may need to compile (e.g. psycopg2
# from stage3, bcrypt). Kept minimal - remove if nothing in
# requirements.txt actually needs a compiler.
# RUN apt-get update && apt-get install -y --no-install-recommends \
#    build-essential \
#    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --timeout 120 -r requirements.txt

# Now copy the application code.
COPY . .

# Overwrite/create frontend/dist with the freshly built assets from
# stage 1 - this is the only artifact we need from that stage, so the
# Node toolchain itself never ships in the final image.
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

EXPOSE 8000

# Render sets $PORT at runtime; default to 8000 for local `docker run`.
ENV PORT=8000
CMD ["sh", "-c", "uvicorn src.orchestrator_api:app --host 0.0.0.0 --port ${PORT}"]