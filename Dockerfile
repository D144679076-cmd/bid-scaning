# bid-scan — production app image (M7). Base = Playwright python image:
# chromium + browser OS deps preinstalled (matches playwright 1.64.1).
FROM mcr.microsoft.com/playwright/python:v1.64.1-noble

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    OLLAMA_BASE=http://host.docker.internal:11434

# repo deps (playwright version matched to base image browsers; pyyaml)
RUN pip install --no-cache-dir pyyaml==6.0.3 playwright==1.64.1

WORKDIR /app

# code — version stamped at build
COPY . /app/
ARG GIT_VERSION=dev
RUN echo "bid-scan ${GIT_VERSION} $(date -u +%F)" > /app/VERSION

# sanity at build: imports resolve
RUN python3 - <<'EOF'
import sys; sys.path.insert(0, '/app')
import sqlite3, yaml  # noqa
from collectors import make_forum, upwork_feed, x_search, linkedin_feed, fb_feed, reddit
from pipeline import bid_writer, followup, safety, classifier, dedup, spam_filter, payment_check
from alerts import telegram, callbacks, digest
print("imports OK")
EOF

CMD ["python3", "services/scheduler.py"]
