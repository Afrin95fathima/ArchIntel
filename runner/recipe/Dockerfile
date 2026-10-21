FROM maven:3.9.9-eclipse-temurin-21 AS build
WORKDIR /src
COPY . .
# The Maven repository is a BuildKit cache shared by all builds, so dependencies download once.
RUN --mount=type=cache,target=/root/.m2 mvn -B -q -ntp package
RUN set -e; f=$(ls target/*.jar | grep -v -- '-plain.jar' | grep -v -- '-sources.jar' | head -1); cp "$f" /app.jar

FROM eclipse-temurin:21-jre
RUN useradd --system --uid 10001 service
COPY --from=build /app.jar /app/app.jar
USER 10001
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/app.jar", "--server.port=8080"]
