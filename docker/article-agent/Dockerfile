# syntax line temporarily disabled due to registry timeout
# syntax=docker/dockerfile:1.4

# LangGraph-based content article agent (no hand-written FastAPI)

FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl \
    # System dependencies for docling OCR (Tesseract)
    tesseract-ocr tesseract-ocr-eng tesseract-ocr-chi-sim libtesseract-dev libleptonica-dev pkg-config \
    # OpenGL libraries required by PyTorch/Docling for image processing
    libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Set Tesseract data path
ENV TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata/

COPY article_agent/requirements.txt /app/requirements.txt

# Install GPU PyTorch first, then docling (需要 NVIDIA GPU 支持)
# 分步执行以隔离错误，并指定 PyTorch Nightly (CUDA 12.8) 以支持 RTX 5090
RUN pip install --upgrade pip
RUN pip install --no-cache-dir --pre torch torchvision --index-url https://download.pytorch.org/whl/nightly/cu128
RUN pip install --no-cache-dir docling

# Set HuggingFace cache directory and mirror for model downloads
# Models will be mounted from host volume at runtime
ENV HF_HOME=/root/.cache/huggingface
ENV HF_ENDPOINT=https://hf-mirror.com

# 利用 BuildKit 的缓存挂载，加速多次构建时的 pip 安装：
# - 依赖列表不变时，该层会命中 Docker 层缓存；
# - 即便 requirements 变更，pip 自身缓存也会通过 /root/.cache/pip 复用。
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r /app/requirements.txt

# 安装 Playwright 及其 Chromium 浏览器依赖（用于 JS 渲染页面抓取）
# 注意：此步骤会增加约 400-500MB 镜像体积
# RUN pip install playwright && playwright install chromium --with-deps

COPY article_agent /app/article_agent

EXPOSE 8130

# 通过 langgraph CLI 启动内容整理 Graph 服务与 Studio：
# - 使用 article_agent/langgraph.json 中定义的 content-deep-agent / content-chat-agent 图；
# - 监听 0.0.0.0:8130 以便 compose 暴露。
CMD ["langgraph", "dev", "--config", "article_agent/langgraph.json", "--host", "0.0.0.0", "--port", "8130"]
