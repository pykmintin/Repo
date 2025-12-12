FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir discord.py requests python-dateutil
COPY bot.py .
CMD ["python", "bot.py"]