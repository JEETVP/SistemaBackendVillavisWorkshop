FROM python:3.12-slim
WORKDIR /app
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home app \
    && mkdir -p /data && chown app:app /data
COPY --chown=app:app services ./services
COPY --chown=app:app scripts ./scripts
USER app
EXPOSE 8000
CMD ["uvicorn", "services.api_gateway.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
