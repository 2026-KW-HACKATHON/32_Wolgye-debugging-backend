FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# asyncpg · psycopg2-binary 는 휠로 설치되므로 gcc / libpq-dev 가 필요 없다
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --create-home --uid 1000 app
USER app

EXPOSE 8000

# slim 이미지에는 curl 이 없어 python 으로 /health 를 부른다
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"

# nginx 뒤에서 돌기 때문에 X-Forwarded-* 헤더를 믿는다
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
