FROM python:3.14-slim-bookworm AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.14-slim-bookworm AS runner

WORKDIR /app
COPY --from=builder /usr/local/lib/python3.14/site-packages /usr/local/lib/python3.14/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

COPY homelab_ai/ ./homelab_ai/
COPY .env.example ./.env.example

VOLUME /app/history
VOLUME /app/plugins

EXPOSE 8000

ENTRYPOINT ["python", "-m", "homelab_ai"]
CMD ["mcp-server", "--host", "0.0.0.0", "--port", "8000"]
