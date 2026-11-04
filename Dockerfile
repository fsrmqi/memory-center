ARG NODE_IMAGE=node:22-alpine
ARG PYTHON_IMAGE=python:3.11-slim
FROM ${NODE_IMAGE} AS frontend
WORKDIR /src/frontend
COPY frontend/package*.json ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
RUN npm run build

FROM ${PYTHON_IMAGE} AS wheel
WORKDIR /src
COPY pyproject.toml MANIFEST.in README.md LICENSE requirements-service.lock ./
COPY memory_center/ memory_center/
COPY docs/ docs/
COPY --from=frontend /src/memory_center/service/static/ memory_center/service/static/
RUN pip download --no-cache-dir --require-hashes -r requirements-service.lock --dest /wheels \
    && pip wheel --no-cache-dir --no-deps --wheel-dir /wheels .

FROM ${PYTHON_IMAGE}
RUN useradd --uid 10001 --create-home memory && mkdir /data && chown memory:memory /data
COPY --from=wheel /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links /wheels memory-center && rm -rf /wheels
USER memory
EXPOSE 8765
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health/ready', timeout=2)"
ENTRYPOINT ["memory-center-service"]
CMD ["--host", "0.0.0.0", "--container-local", "--data-dir", "/data"]
