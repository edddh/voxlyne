# Ascolta - Dockerfile
# Multi-stage: admin-ui (Node) buildata prima, poi copiata nell'immagine
# Python che la serve (app/main.py monta admin-ui/dist come StaticFiles -
# senza questo stage l'immagine parte ma l'admin UI risponde 404).

FROM node:20-slim AS admin-ui-builder

WORKDIR /build/admin-ui

COPY admin-ui/package.json admin-ui/package-lock.json ./
RUN npm ci

COPY admin-ui/ ./
RUN npm run build


FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libffi8 \
    libjpeg62-turbo \
    libpng16-16 \
    libfontconfig1 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# admin-ui/ è escluso dal contesto (vedi .dockerignore): la dist buildata
# nello stage precedente arriva qui esplicitamente.
COPY --from=admin-ui-builder /build/admin-ui/dist ./admin-ui/dist

# Create directories for data persistence
RUN mkdir -p /app/data /app/logs

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
