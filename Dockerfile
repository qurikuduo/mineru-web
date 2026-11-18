# MinerU Web Console
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    MINERU_WEB_DATA_DIR=/data \
    TZ=Asia/Shanghai

# Build-time network: this RUN step does NOT inherit the daemon proxy.
# Clear any proxy and pull pip deps straight from the aliyun mirror
# (small packages, direct TCP to aliyun is reachable in this env).
ENV HTTP_PROXY="" HTTPS_PROXY="" http_proxy="" https_proxy=""

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir \
        -i https://mirrors.aliyun.com/pypi/simple/ \
        --trusted-host mirrors.aliyun.com \
        -r requirements.txt

COPY app ./app

RUN mkdir -p /data/config /data/results /data/logs

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
