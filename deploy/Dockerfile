FROM python:3.11-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 OPENBLAS_NUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=4 MALLOC_ARENA_MAX=2 \
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
    PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True \
    MPLCONFIGDIR=/tmp/matplotlib HOME=/tmp
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils libgl1 libglib2.0-0 libgomp1 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY deploy/requirements.lock /app/requirements.lock
RUN pip install --no-cache-dir torch==2.13.0+cpu torchvision==0.28.0+cpu --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.lock \
    && pip check
COPY module /app/module
COPY utils /app/utils
COPY fastocr /app/fastocr
COPY server/__init__.py server/schemas.py server/security.py server/uat.py /app/server/
COPY conf/uat.yaml /app/conf/uat.yaml
COPY models /app/models
RUN useradd --uid 10001 --no-create-home ocr \
    && python -c "from server.uat import app; print('UAT imports OK')"
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3)"
CMD ["uvicorn", "server.uat:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
