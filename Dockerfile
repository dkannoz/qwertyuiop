FROM python:3.11-slim-buster
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements.txt
EXPOSE 7860
CMD uvicorn run:main_app --host 0.0.0.0 --port $PORT --workers 4
