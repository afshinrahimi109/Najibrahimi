FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_PATH=/app/data/drafts.sqlite3

WORKDIR /app
RUN mkdir -p /app/data

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY app.py database.py holo.py ./

CMD ["python", "app.py"]
