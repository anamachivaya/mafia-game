# Dockerfile
FROM python:3.11-slim

# System prep (optional but good hygiene)
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

WORKDIR /app
COPY app.py /app/app.py

# Install deps
RUN pip install --no-cache-dir flask

# Flask listens on 5000 inside the container
EXPOSE 5000

# Start the app
CMD ["python", "app.py"]