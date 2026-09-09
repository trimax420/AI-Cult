FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir \
    "google-adk==2.8.0" \
    "google-genai==2.22.0" \
    "mcp==1.29.1" \
    "opentelemetry-exporter-otlp-proto-http>=1.39.0,<2.0.0"
COPY production_director_agent ./production_director_agent
RUN pip install --no-cache-dir --no-deps .
EXPOSE 8090
CMD ["adk", "web", "--host", "0.0.0.0", "--port", "8090", "."]
