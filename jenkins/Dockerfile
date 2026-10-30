# Local Jenkins for learning/demo: Jenkins LTS + Python + Docker CLI (talks to the host's
# Docker through a mounted socket) + the plugins our Jenkinsfile uses.
# Build:  docker build -t drqa-jenkins jenkins/
# Run:    see docs/JENKINS.md
FROM jenkins/jenkins:lts-jdk21

USER root
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-venv git \
 && rm -rf /var/lib/apt/lists/*
# Docker CLI + buildx (BuildKit is required by our Dockerfile's COPY --chmod)
COPY --from=docker:27-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker:27-cli /usr/local/libexec/docker/cli-plugins/docker-buildx /usr/local/libexec/docker/cli-plugins/docker-buildx

USER jenkins
# workflow-aggregator = Pipeline; the others back Jenkinsfile steps:
# git (checkout scm), junit (junit), timestamper (timestamps()), credentials-binding (withCredentials)
RUN jenkins-plugin-cli --plugins workflow-aggregator git junit timestamper credentials-binding
