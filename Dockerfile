FROM python:3.11-slim-bookworm

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 7860

CMD exec uvicorn run:main_app --host 0.0.0.0 --port ${PORT:-7860} --workers 4
