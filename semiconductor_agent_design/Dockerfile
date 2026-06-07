FROM python:3.11-slim

WORKDIR /workspace

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY arxiv_query_set.yaml ./arxiv_query_set.yaml

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "app.jobs"]
