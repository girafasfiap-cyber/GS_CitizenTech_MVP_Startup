#!/bin/bash
# Inicialização no Azure App Service (Linux, runtime Python).
# 1) instala o Tesseract (OCR da leitura de contas) se ainda não existir;
# 2) sobe o CidadeViva com uvicorn.
set -e
cd /home/site/wwwroot

if ! command -v tesseract >/dev/null 2>&1; then
  echo "[startup] instalando Tesseract OCR (pt)..."
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends \
    tesseract-ocr tesseract-ocr-por libglib2.0-0
fi

# garante o ambiente virtual criado no build (Oryx)
if [ -f antenv/bin/activate ]; then . antenv/bin/activate; fi

echo "[startup] subindo o CidadeViva"
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" \
  --proxy-headers --forwarded-allow-ips='*'
