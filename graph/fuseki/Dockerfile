FROM eclipse-temurin:21-jre-jammy

ARG JENA_VERSION=6.2.0
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && curl -fsSL -o /tmp/jena.tar.gz "https://archive.apache.org/dist/jena/binaries/apache-jena-${JENA_VERSION}.tar.gz" \
    && curl -fsSL -o /tmp/fuseki.tar.gz "https://archive.apache.org/dist/jena/binaries/apache-jena-fuseki-${JENA_VERSION}.tar.gz" \
    && tar -xzf /tmp/jena.tar.gz -C /opt \
    && tar -xzf /tmp/fuseki.tar.gz -C /opt \
    && rm /tmp/jena.tar.gz /tmp/fuseki.tar.gz \
    && rm -rf /var/lib/apt/lists/*

ENV JENA_VERSION=${JENA_VERSION}
ENV JENA_HOME=/opt/apache-jena-${JENA_VERSION}
ENV FUSEKI_HOME=/opt/apache-jena-fuseki-${JENA_VERSION}
ENV PATH="${JENA_HOME}/bin:${FUSEKI_HOME}:${PATH}"

EXPOSE 3030
