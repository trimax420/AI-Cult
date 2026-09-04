FROM python:3.12-alpine
WORKDIR /app
COPY provision.py .
COPY dashboards/ai-production-director.json /config/dashboard.json
COPY alerting/rules.json /config/rules.json
CMD ["python", "provision.py"]
