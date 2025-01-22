# base docker with python, poetry and all base requirements
FROM python:3.12.6-slim as reqs
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*
WORKDIR /
ENV \
  PYTHONFAULTHANDLER=1 \
  PYTHONUNBUFFERED=1 \
  PYTHONDONTWRITEBYTECODE=1 \
  PIP_NO_CACHE_DIR=off \
  PIP_DISABLE_PIP_VERSION_CHECK=on \
  PIP_DEFAULT_TIMEOUT=100

# install poetry
ARG POETRY_VERSION=1.8.2
ARG POETRY_HOME="/opt/poetry"
RUN curl -sSL https://install.python-poetry.org | python - --version ${POETRY_VERSION} && \
    ln -s ${POETRY_HOME}/bin/poetry /usr/local/bin/poetry

# Copy only requirements to cache them in docker layer
WORKDIR /app
COPY poetry.lock pyproject.toml /app/

# Project initialization (poetry):
## gcc and g++ are needed to build some of the requirements, but later are removed to reduce image size
RUN apt-get update && apt-get install -y --no-install-recommends gcc g++ protobuf-compiler \
    && poetry config virtualenvs.create false \
    && poetry install --only main --no-interaction --no-ansi --no-cache \
    && apt-get remove -y --purge gcc g++ \
    && apt-get autoremove -y \
    && rm -rf /root/.cache /var/lib/apt/lists/*

FROM reqs as proto_build
WORKDIR /app
COPY proto/cloud proto/cloud
# RUN rm /app/proto/cloud/*.pyi
RUN rm /app/proto/cloud/*.py
RUN rm /app/proto/cloud/*.pyi
RUN protoc -I=./ --python_out=./ ./proto/cloud/*.proto
RUN protoc -I=./ --python_out=pyi_out:./ ./proto/cloud/*.proto


# dev image with all dependencies (for local development)
FROM proto_build AS final_image
WORKDIR /app
RUN poetry install --no-interaction --no-ansi --no-cache && rm -rf /root/.cache
COPY . /app
CMD python stuff.py

