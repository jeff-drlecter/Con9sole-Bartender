FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928
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
