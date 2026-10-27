FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Editable install: compose bind-mounts the source over /app, so the running app uses the live code.
COPY pyproject.toml LICENSE ./
COPY kb ./kb
RUN pip install -e .

EXPOSE 8000
CMD ["uvicorn", "kb.app:app", "--host", "0.0.0.0", "--port", "8000"]
