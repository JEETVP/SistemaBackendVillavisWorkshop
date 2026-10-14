FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services ./services

ENV PYTHONPATH=/app

CMD ["uvicorn", "services.api_gateway.app:app", "--host", "0.0.0.0", "--port", "8000"]
