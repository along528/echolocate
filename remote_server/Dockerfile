FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

# Cloud Run sets PORT env var, default to 8080
ENV PORT=8080
EXPOSE 8080

# Run the MCP server
CMD ["python", "main.py"]
