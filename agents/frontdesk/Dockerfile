# Bugline front desk agent. Built and run by the `frontdesk` service in the root docker-compose.yml.
FROM python:3.14.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./
COPY prompts ./prompts

# state/ holds the Switch credentials, connection ids, tickets and calls.log; compose mounts a
# named volume here so they survive a rebuild.
RUN useradd --create-home bugline && mkdir state && chown bugline state
USER bugline

CMD ["python", "agent.py"]
