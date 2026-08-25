FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
# The container runs as the host's uid (see docker-compose.yml), which cannot
# write into /srv, so stop Python trying to cache bytecode there.
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    VAULT_DB=/data/vault.db VAULT_CONTENT=/data/content VAULT_INBOX=/data/inbox
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
