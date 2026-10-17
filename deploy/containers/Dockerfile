# SentinelWard service image for IBM LinuxONE (s390x). One image, one service per container.
# Scientific Python comes from Ubuntu's s390x packages (same as the bare-metal server; pip has no
# trustworthy s390x builds for them). Only pure-Python packages come from pip.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
    PSYCOPG_IMPL=python

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      python3 python3-venv python3-pip \
      python3-numpy python3-scipy python3-pandas python3-sklearn python3-yaml python3-psutil \
      libpq5 libsndfile1 ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 sw

WORKDIR /app
# requirements-container.txt = requirements-server.txt minus wfdb (pack building only; its deps need
# a compiler on s390x). Keeps the final image compiler-free.
COPY deploy/containers/requirements-container.txt /tmp/requirements-container.txt
RUN python3 -m venv --system-site-packages /venv \
 && /venv/bin/pip install --no-cache-dir -r /tmp/requirements-container.txt websockets

COPY common/ common/
COPY simulator/ simulator/
COPY brain/ brain/
COPY attacks/ attacks/
COPY backend/ backend/
RUN /venv/bin/pip install --no-cache-dir --no-deps -e ./common -e ./simulator -e ./brain -e ./attacks -e ./backend \
 && /venv/bin/python -c "import sw_common, sw_sim, sw_brain, sw_attacks, sw_api" \
 && mkdir -p /runs && chown sw:sw /runs

ENV PATH=/venv/bin:$PATH
USER sw
