FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY echo_locate.py .

RUN useradd -m -u 1000 appuser
USER appuser

EXPOSE 8080

CMD ["python", "main.py"]
