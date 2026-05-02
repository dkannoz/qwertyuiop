FROM python:3.11-slim-bookworm

WORKDIR /app

# ffmpeg used by exoplayer_remux for fast audio reencode (Vavoo 44.1kHz fix)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 7860

CMD exec uvicorn run:main_app --host 0.0.0.0 --port ${PORT:-7860} --workers 4
