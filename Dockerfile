FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-por libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app app
COPY citizen_vision citizen_vision
COPY seeds seeds
COPY static static
RUN useradd -m app && mkdir -p /home/data && chown -R app /home/data
USER app
ARG GIT_SHA=dev
ENV APP_VERSION=$GIT_SHA
ENV DATA_DIR=/home/data PORT=8000 WEBSITES_PORT=8000
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request,os;urllib.request.urlopen('http://localhost:'+os.getenv('PORT','8000')+'/health')"
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
