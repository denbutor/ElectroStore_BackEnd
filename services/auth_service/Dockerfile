FROM python:3.11-slim

# Встановлюємо uv для надшвидкого керування залежностями
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Копіюємо файл конфігурації проєкту
COPY pyproject.toml .

# Встановлюємо залежності в системне оточення контейнера
RUN uv pip install --system --no-cache -r pyproject.toml

# Копіюємо вихідний код
COPY app ./app

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]