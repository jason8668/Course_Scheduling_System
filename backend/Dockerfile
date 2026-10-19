# 后端映像:两个 target。
#   base   → api 服务(精简)
#   worker → 背景任务(额外装 WeasyPrint 系统依赖/中文字型与 PostgreSQL client)
# 明确锁 trixie:其 main 内含 postgresql-client(17),pg_dump 可备份 v16 服务器。
FROM python:3.12-slim-trixie AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# curl 供 healthcheck 使用;postgresql-client 供「结构升级前自动备份」(v1.3.0)——
# 迁移在 api 容器启动时执行,备份必须在同一个容器、迁移之前完成。
RUN apt-get update && apt-get install -y --no-install-recommends curl postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# 先装相依(利用 layer 快取)
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

# 应用程序原始码
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

# 系统版本(v1.2.3):CI 打版本标签时以 --build-arg APP_VERSION=v1.2.3 注入,
# 系统管理页据此显示目前版本并判断是否有新版。放在最后,改版号不会让前面的层失效。
ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
CMD ["api"]

# ── worker:PDF 导出的重量级原生依赖只装在这里,api 映像维持精简 ──
# WeasyPrint 需 Pango/Cairo/gdk-pixbuf;中文内嵌字型用 Noto CJK;
# poppler-utils 供导出 PNG 与验证用(PDF→影像)。
FROM base AS worker

# PDF/PNG(WeasyPrint + poppler + 中文字型)+ 备份(postgresql-client,M5-2)。
# trixie 的 postgresql-client 为 17,可 pg_dump/pg_restore 对上 postgres:16 服务器
# (client ≥ server 允许;server 较新才是不支援的方向)。
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libpangoft2-1.0-0 \
        libgdk-pixbuf-2.0-0 \
        libcairo2 \
        libffi8 \
        libjpeg62-turbo \
        fonts-noto-cjk \
        poppler-utils \
        postgresql-client \
    && rm -rf /var/lib/apt/lists/*

RUN pip install '.[export]'

CMD ["worker"]
