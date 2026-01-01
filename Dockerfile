FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY core ./core
COPY api ./api
COPY templates ./templates
COPY static ./static
COPY main.py ./

EXPOSE 5000

CMD ["gunicorn", "-b", "0.0.0.0:5000", "main:app"]
