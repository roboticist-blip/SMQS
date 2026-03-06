FROM python:3.11-slim

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir \
    fastapi \
    uvicorn \
    influxdb-client \
    paho-mqtt

CMD ["python", "main.py"]