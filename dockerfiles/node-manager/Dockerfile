FROM python:3.12-slim


ARG BUILD_MODE="dev"
ARG RUN_AS="root"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    iputils-ping \
    libcap2-bin \
    && setcap cap_net_raw+ep /bin/ping \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml poetry.lock ./


RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir poetry \
    && POETRY_VIRTUALENVS_CREATE=false poetry install --only=main,node-manager --no-root \
    && pip uninstall -y poetry || true

COPY src ./

# Copy pre-built UI assets from the repository build output into the image.
# The Docker build context must contain "dist/kitchen-ui" (run `npm run build`
# at repo root before building the image). This COPY will fail if the path is
# not present in the build context, which is intentional to avoid shipping an
# image with missing UI assets.
COPY dist/kitchen-ui /app/dist/kitchen-ui

RUN mkdir -p /app/logs

# Conditionally create a named non-root user (only if prod & not root)
RUN if [ "$BUILD_MODE" = "prod" ] && [ "$RUN_AS" != "root" ]; then \
            groupadd -r "$RUN_AS" && useradd -r -g "$RUN_AS" "$RUN_AS" && \
            chown -R "$RUN_AS":"$RUN_AS" /app ; \
        fi

USER ${RUN_AS}

EXPOSE 8000

CMD ["python", "-m", "kitchen.node_manager.main"]