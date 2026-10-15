# Build with immutable Maven and JDK base digests. Provision tools without any
# customer source mounted; the application runs this image with network=none.
ARG MAVEN_BASE
ARG JDK_BASE
FROM ${MAVEN_BASE} AS tools
WORKDIR /tools
COPY pom.xml ./pom.xml
RUN mvn -B org.apache.maven.plugins:maven-dependency-plugin:3.8.1:copy-dependencies -DoutputDirectory=/tools/lib
FROM ${JDK_BASE}
COPY --from=tools /tools/lib/ /opt/security/lib/
COPY include.xml /opt/security/include.xml
USER 1000:1000
WORKDIR /work
ENTRYPOINT ["/bin/sh"]
