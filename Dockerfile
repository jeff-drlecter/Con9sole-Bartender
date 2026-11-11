FROM python:3.11-slim@sha256:07d4824036af339fa1b6ef769cc99d9c10a141769538b52b3b597c84f7a7b535
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.txt

RUN groupadd --gid 10001 bartender && useradd --uid 10001 --gid bartender --no-create-home bartender

COPY . .

ENTRYPOINT ["python", "scripts/container_entrypoint.py"]
CMD ["python", "bot.py"]
