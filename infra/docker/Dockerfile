FROM node:22-alpine AS frontend
WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci --legacy-peer-deps
COPY frontend/ ./
RUN npm run build

FROM eclipse-temurin:21-jdk-jammy AS java

FROM python:3.12-slim
COPY --from=java /opt/java/openjdk /opt/java/openjdk
ENV JAVA_HOME=/opt/java/openjdk
ENV JQASSISTANT_HOME=/app/.runtime/jqassistant/jqassistant-commandline-neo4jv5-2.7.0
ENV PYTHONHASHSEED=0
ENV PYTHONPATH=/app/backend
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl unzip git && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.lock /app/backend/requirements.lock
RUN pip install --no-cache-dir -r /app/backend/requirements.lock
RUN mkdir -p /app/.runtime/jqassistant /app/.runtime/exporter && curl -fsSL https://repo.maven.apache.org/maven2/com/buschmais/jqassistant/cli/jqassistant-commandline-neo4jv5/2.7.0/jqassistant-commandline-neo4jv5-2.7.0-distribution.zip -o /tmp/jqa.zip && unzip -q /tmp/jqa.zip -d /app/.runtime/jqassistant && rm /tmp/jqa.zip
COPY backend /app/backend
RUN /opt/java/openjdk/bin/javac --release 17 -proc:none -cp "$JQASSISTANT_HOME/lib/*" -d /app/.runtime/exporter /app/backend/scanner-java/ExportGraph.java
COPY samples /app/samples
COPY scripts /app/scripts
COPY runner/recipe /app/runner/recipe
COPY docs /app/docs
COPY --from=frontend /build/frontend/dist /app/frontend/dist
RUN useradd --create-home archintel && mkdir -p /app/.data && chown -R archintel:archintel /app
USER archintel
EXPOSE 8000
CMD ["uvicorn", "app.main:create_app", "--factory", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000"]
