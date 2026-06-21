# syntax=docker/dockerfile:1.7
# -----------------------------------------------------------------------------
# ArdaLink Engine — multi-stage build
# Final image: distroless Python 3.12
# -----------------------------------------------------------------------------

# ---- Stage 1: deps via uv ----
FROM python:3.12-slim AS deps
WORKDIR /app
RUN pip install --no-cache-dir uv==0.5.10
COPY pyproject.toml uv.lock ./
COPY ardalink_engine ./ardalink_engine
RUN uv export --no-hashes --frozen > /tmp/requirements.txt && \
    pip install --no-cache-dir -r /tmp/requirements.txt

# ---- Stage 2: runtime ----
FROM gcr.io/distroless/python3.12-debian12:nonroot AS runtime
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ARDALINK_HOST=0.0.0.0 \
    ARDALINK_PORT=5001
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin
COPY ardalink_engine ./ardalink_engine
COPY migrations ./migrations
USER nonroot
EXPOSE 5001
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; r=urllib.request.urlopen('http://127.0.0.1:5001/health',timeout=2); sys.exit(0 if r.status==200 else 1)"]
ENTRYPOINT ["python", "-m", "ardalink_engine.main"]