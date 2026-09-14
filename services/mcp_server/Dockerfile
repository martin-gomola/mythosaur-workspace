FROM python:3.12-slim

WORKDIR /app

COPY services/mcp_server/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY services /app/services

EXPOSE 8066

CMD ["uvicorn", "services.mcp_server.app:app", "--host", "0.0.0.0", "--port", "8066", "--no-access-log"]
