FROM python:3.11-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VOICE_CASCADE_DATA_DIR=/tmp/voice-cascade-lab

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY fixtures ./fixtures

RUN pip install --no-cache-dir .

CMD ["python", "-m", "voice_cascade", "demo"]
