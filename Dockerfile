FROM python:3.12-slim

ARG VERSION=0.3.0
ARG REVISION=unknown
LABEL org.opencontainers.image.source="https://github.com/leodenglovescode/Finstalgia" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version=$VERSION \
      org.opencontainers.image.revision=$REVISION

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FINSTALGIA_CONFIG_DIR=/config

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY finstalgia/ finstalgia/
RUN python -m pip install . \
    && groupadd --gid 10001 finstalgia \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /config finstalgia \
    && mkdir /config \
    && chown 10001:10001 /config \
    && chmod 0700 /config

USER 10001:10001
EXPOSE 18095
ENTRYPOINT ["python", "-m", "finstalgia"]
CMD ["serve", "--no-env-file", "--host", "0.0.0.0", "--port", "18095"]
