FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Utilisateur non-root (uid 1001 = propriétaire des volumes sur l'hôte)
RUN useradd -u 1001 -m appuser 2>/dev/null || useradd -m appuser; chown -R appuser:appuser /app
USER appuser
EXPOSE 5000
CMD ["gunicorn", "-w", "4", "-t", "300", "-b", "0.0.0.0:5000", "run:app"]
