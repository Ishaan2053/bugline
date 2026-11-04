# Bugline front desk agent. Built and run by the `frontdesk` service in the root docker-compose.yml.
# The build context is agents/, so the shared `common` package sits next to the agent as it
# does in the repo.
FROM python:3.14.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app/frontdesk
COPY common/requirements.txt ../common/
COPY frontdesk/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY common/*.py ../common/
COPY frontdesk/*.py ./
COPY frontdesk/prompts ./prompts

# state/ holds the Switch credentials, connection ids, tickets and calls.log; compose mounts a
# named volume here so they survive a rebuild.
RUN useradd --create-home bugline && mkdir state && chown bugline state
USER bugline

CMD ["python", "agent.py"]
