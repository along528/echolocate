FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

# Environment variables to disable MCP host validation
# Cloud Run handles security at the load balancer level
ENV MCP_ENABLE_HOST_VALIDATION=false
ENV ENABLE_HOST_VALIDATION=false

EXPOSE 8080

CMD ["python", "main.py"]
