FROM python:3.12-slim
ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PLAYWRIGHT_BROWSERS_PATH=/ms-playwright PIP_INDEX_URL=${PIP_INDEX_URL} PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY backend/requirements.txt .
RUN python -m pip install --no-cache-dir --index-url "$PIP_INDEX_URL" --retries 10 --timeout 60 -r requirements.txt && python -m playwright install --with-deps chromium firefox webkit
RUN useradd --create-home --uid 10001 adbot && mkdir -p /app/data/screenshots && chown -R adbot:adbot /app /ms-playwright
COPY --chown=adbot:adbot backend/ .
USER adbot
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers", "--no-server-header", "--no-access-log"]
