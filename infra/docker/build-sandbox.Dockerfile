# Operator-supplied immutable image digests are required. This is separate from
# the ArchIntel application image and must not contain credentials/customer data.
ARG MAVEN_BASE
ARG JDK_BASE
FROM ${MAVEN_BASE} AS maven
WORKDIR /refactor
COPY refactor/pom.xml ./pom.xml
COPY refactor/src/ ./src/
RUN mvn -B -DskipTests package
FROM ${JDK_BASE}
COPY --from=maven /usr/share/maven /usr/share/maven
ENV PATH="/usr/share/maven/bin:${PATH}"
COPY maven-repository/ /opt/m2/
COPY --from=maven /refactor/target/archintel-refactor-1.0.0.jar /opt/archintel/refactor/refactor.jar
COPY --from=maven /refactor/target/lib/ /opt/archintel/refactor/lib/
RUN chmod -R a+rX /opt/m2 /usr/share/maven
USER 1000:1000
WORKDIR /work
ENTRYPOINT ["/bin/sh"]
