FROM python:3.12-slim

# Logs saem na hora no painel do Render (sem buffer do Python)
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .

# Não roda como root dentro do container
RUN useradd --create-home appuser
USER appuser

ENV PORT=8080
EXPOSE 8080

# Escuta na porta que o Render passar em $PORT (8080 se não vier nada),
# assim a porta do gunicorn e a do Render nunca ficam diferentes.
CMD exec gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 1 --threads 4 --timeout 60 app:app
