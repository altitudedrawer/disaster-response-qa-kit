// Declarative pipeline: checkout -> install -> test -> build image -> test inside image.
// Needs an agent with python3 (+venv) and the docker CLI. See docs/JENKINS.md to run Jenkins locally.
pipeline {
    agent any

    options {
        timestamps()
        timeout(time: 20, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '10'))
    }

    parameters {
        booleanParam(name: 'RUN_CONTRACT_TESTS', defaultValue: false,
                     description: 'Run live ArcGIS contract tests (needs Jenkins credential "feature-service-url")')
    }

    environment {
        IMAGE = "drqa:${env.BUILD_NUMBER}"
        PIP_DISABLE_PIP_VERSION_CHECK = '1'
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
                sh 'git log -1 --oneline'
            }
        }

        stage('Install') {
            steps {
                sh '''
                    python3 -m venv .venv
                    . .venv/bin/activate
                    pip install -q -r requirements.txt
                    python --version
                '''
            }
        }

        stage('Unit + pipeline tests') {
            steps {
                sh '''
                    . .venv/bin/activate
                    mkdir -p reports
                    python -m pytest -v -rs --junitxml=reports/junit.xml
                '''
            }
        }

        stage('Contract tests (live ArcGIS)') {
            when { expression { params.RUN_CONTRACT_TESTS } }
            steps {
                withCredentials([string(credentialsId: 'feature-service-url', variable: 'FEATURE_SERVICE_URL')]) {
                    sh '''
                        . .venv/bin/activate
                        python -m pytest tests/contract -v --junitxml=reports/junit-contract.xml
                    '''
                }
            }
        }

        stage('Build image') {
            steps {
                sh 'docker build -t "$IMAGE" .'
            }
        }

        stage('Test inside image') {
            steps {
                sh 'docker run --rm "$IMAGE" test -q'
                sh 'docker run --rm "$IMAGE" demo'
            }
        }
    }

    post {
        always {
            junit allowEmptyResults: true, testResults: 'reports/*.xml'
        }
        cleanup {
            sh 'docker image rm -f "$IMAGE" || true'
        }
    }
}
