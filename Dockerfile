FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .

# registry + .env + state are mounted/injected at runtime (compose)
EXPOSE 8085
CMD ["python", "-m", "chat_gateway", "serve"]
