pipeline {
  agent any

  environment {
    REGISTRY         = "docker.io/swaroop4"
    IMAGE_TAG        = "${env.GIT_COMMIT ?: 'dev'}"
    APP_NAME         = "sentinelcare"
    MODEL_PATH       = "models/mock_artifacts/sepsis_mock_model.json"
    COMPOSE_SERVICES = "backend frontend patients vitals alerts scoring auth tasks audit simulator notifications mongo"
    K8S_NAMESPACE    = "sentinelcare"
    HELM_CHART_PATH  = "infra/helm/sentinelcare"
    MICROSERVICES    = "patients vitals alerts scoring simulator auth tasks audit notifications"
    SONAR_HOST_URL   = "http://localhost:9000"
    FRONTEND_API_BASE = "http://localhost:30081"
  }

  options {
    timestamps()
    ansiColor('xterm')
    buildDiscarder(logRotator(numToKeepStr: '15'))
  }

  stages {
    stage('Checkout') {
      steps {
        checkout scm
        sh 'git status -sb'
      }
    }

    stage('Static Analysis') {
      steps {
        sh '''
          python -m venv .venv
          . .venv/bin/activate
          pip install --upgrade pip
          pip install -r backend/requirements.txt ruff black mypy bandit pip-audit
          ruff check backend
          black --check backend
          mypy backend || true        # allow partial typing while we evolve
          bandit -r backend || true   # best-effort SAST
          pip-audit -r backend/requirements.txt || true
          cd frontend && corepack enable && pnpm install --frozen-lockfile && pnpm run lint
        '''
    }
  }

    stage('Unit Tests') {
      steps {
        sh '''
          . .venv/bin/activate
          pip install pytest pytest-asyncio
          PYTHONPATH=backend python -m pytest backend/tests
          cd frontend && pnpm test -- --watch=false
        '''
      }
    }

    stage('SonarQube Analysis') {
      steps {
        withCredentials([string(credentialsId: 'sonar-token', variable: 'SONAR_TOKEN')]) {
          sh '''
            sonar-scanner \
            -Dsonar.projectKey=sentinelcare \
              -Dsonar.sources=backend/app,frontend/src \
              -Dsonar.tests=backend/tests \
              -Dsonar.exclusions=backend/tests/** \
              -Dsonar.host.url=${SONAR_HOST_URL} \
              -Dsonar.login=${SONAR_TOKEN} \
              -Dsonar.python.version=3.11
          '''
        }
      }
    }

    stage('Secret Scan') {
      steps {
        sh '''
          command -v gitleaks >/dev/null 2>&1 || echo "gitleaks not installed on agent"
          if command -v gitleaks >/dev/null 2>&1; then gitleaks detect --no-git -v; fi
        '''
      }
    }

    stage('Mock Model Validation') {
      steps {
        sh '''
          test -f ${MODEL_PATH}
          sha256sum ${MODEL_PATH}
          . .venv/bin/activate
          PYTHONPATH=backend python - <<PY
from pathlib import Path
from app.services.mock_model import MockRiskModel

artifact = Path("${MODEL_PATH}")
model = MockRiskModel(artifact)
payload = {
    "heart_rate": 130,
    "respiratory_rate": 26,
    "systolic_bp": 90,
    "diastolic_bp": 50,
    "spo2": 90,
    "temperature_c": 39,
}
score, label = model.score(payload)
assert 0 <= score <= 1
print("Mock model OK", score, label)
PY
        '''
      }
    }

    stage('Build & Up (Compose)') {
      steps {
        sh '''
          docker compose build ${COMPOSE_SERVICES}
          docker compose up -d ${COMPOSE_SERVICES}
        '''
      }
    }

    stage('Smoke Tests') {
      steps {
        sh '''
          set -euo pipefail

          wait_for_http() {
            local url="$1"
            local tries=0
            until curl -fsI "$url" >/dev/null; do
              tries=$((tries + 1))
              if [ "$tries" -ge 15 ]; then
                curl -I "$url"
                return 1
              fi
              sleep 2
            done
          }

          wait_for_http http://localhost:8001/health
          TOKEN=$(curl -s -X POST http://localhost:8001/auth/login -H "Content-Type: application/json" -d '{"username":"admin@sentinel.care","password":"admin123"}' | jq -r .access_token)
          curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8001/patients | head -c 200
          wait_for_http http://localhost:8081
        '''
      }
    }

    stage('Build Images (for registry)') {
      steps {
        sh '''
          docker build -f backend/Dockerfile -t ${REGISTRY}/${APP_NAME}-backend:${IMAGE_TAG} .
          docker build -f frontend/Dockerfile -t ${REGISTRY}/${APP_NAME}-frontend:${IMAGE_TAG} . \
            --build-arg VITE_API_BASE=${FRONTEND_API_BASE}
          for svc in patients vitals alerts scoring simulator auth tasks audit notifications; do
            docker build -f services/$svc/Dockerfile -t ${REGISTRY}/${APP_NAME}-${svc}:${IMAGE_TAG} .
          done
        '''
      }
    }

    stage('Image Scan') {
      steps {
        sh '''
          set -euo pipefail

          TRIVY_BIN="$(command -v trivy || true)"
          if [ -z "${TRIVY_BIN}" ]; then
            if [ -x /home/swaroop/bin/trivy ]; then
              TRIVY_BIN=/home/swaroop/bin/trivy
            else
              TOOLS_DIR="${WORKSPACE:-.}/.tools/trivy"
              mkdir -p "${TOOLS_DIR}"
              if [ ! -x "${TOOLS_DIR}/trivy" ]; then
                echo "Installing Trivy locally for this workspace..."
                curl -sSL -o "${TOOLS_DIR}/trivy.tar.gz" https://github.com/aquasecurity/trivy/releases/download/v0.55.2/trivy_0.55.2_Linux-64bit.tar.gz
                tar -xzf "${TOOLS_DIR}/trivy.tar.gz" -C "${TOOLS_DIR}" trivy
                rm -f "${TOOLS_DIR}/trivy.tar.gz"
                chmod +x "${TOOLS_DIR}/trivy"
              fi
              TRIVY_BIN="${TOOLS_DIR}/trivy"
            fi
          fi

          IMAGES="${REGISTRY}/${APP_NAME}-backend:${IMAGE_TAG} ${REGISTRY}/${APP_NAME}-frontend:${IMAGE_TAG}"
          for svc in ${MICROSERVICES}; do
            IMAGES="${IMAGES} ${REGISTRY}/${APP_NAME}-${svc}:${IMAGE_TAG}"
          done

          for img in ${IMAGES}; do
            "${TRIVY_BIN}" image --severity HIGH,CRITICAL "$img"
          done
        '''
      }
    }

    stage('Push Images') {
      when {
        expression {
          sh(script: "git branch -r --contains HEAD | grep -q 'origin/main'", returnStatus: true) == 0
        }
      }
      steps {
        withCredentials([usernamePassword(credentialsId: 'dockerhub-creds', usernameVariable: 'DOCKER_USER', passwordVariable: 'DOCKER_PASS')]) {
          sh '''
            echo "${DOCKER_PASS}" | docker login -u "${DOCKER_USER}" --password-stdin
            for svc in backend frontend patients vitals alerts scoring simulator auth tasks audit notifications; do
              docker push ${REGISTRY}/${APP_NAME}-${svc}:${IMAGE_TAG}
            done
          '''
        }
      }
    }

    stage('Pull & Deploy to K8s') {
      when {
        expression {
          sh(script: "git branch -r --contains HEAD | grep -q 'origin/main'", returnStatus: true) == 0
        }
      }
      steps {
        catchError(buildResult: 'SUCCESS', stageResult: 'FAILURE') {
          withCredentials([file(credentialsId: 'kubeconfig', variable: 'KUBECONFIG')]) {
            sh '''
              # Pull images from registry to validate availability
              for svc in backend frontend patients vitals alerts scoring simulator auth tasks audit notifications; do
                docker pull ${REGISTRY}/${APP_NAME}-${svc}:${IMAGE_TAG}
              done

              # Helm deploy using pulled image tags (cluster must be configured on agent)
              helm upgrade --install ${APP_NAME} ${HELM_CHART_PATH} \
                --namespace ${K8S_NAMESPACE} --create-namespace \
                --set global.environment=dev \
                --set image.backend.repository=${REGISTRY}/${APP_NAME}-backend \
                --set image.backend.tag=${IMAGE_TAG} \
                --set image.frontend.repository=${REGISTRY}/${APP_NAME}-frontend \
                --set image.frontend.tag=${IMAGE_TAG} \
                --set image.patients.repository=${REGISTRY}/${APP_NAME}-patients \
                --set image.patients.tag=${IMAGE_TAG} \
                --set image.vitals.repository=${REGISTRY}/${APP_NAME}-vitals \
                --set image.vitals.tag=${IMAGE_TAG} \
                --set image.alerts.repository=${REGISTRY}/${APP_NAME}-alerts \
                --set image.alerts.tag=${IMAGE_TAG} \
                --set image.scoring.repository=${REGISTRY}/${APP_NAME}-scoring \
                --set image.scoring.tag=${IMAGE_TAG} \
                --set image.auth.repository=${REGISTRY}/${APP_NAME}-auth \
                --set image.auth.tag=${IMAGE_TAG} \
                --set image.tasks.repository=${REGISTRY}/${APP_NAME}-tasks \
                --set image.tasks.tag=${IMAGE_TAG} \
                --set image.audit.repository=${REGISTRY}/${APP_NAME}-audit \
                --set image.audit.tag=${IMAGE_TAG} \
                --set image.notifications.repository=${REGISTRY}/${APP_NAME}-notifications \
                --set image.notifications.tag=${IMAGE_TAG} \
                --set image.simulator.repository=${REGISTRY}/${APP_NAME}-simulator \
                --set image.simulator.tag=${IMAGE_TAG}

              kubectl rollout status deploy/${APP_NAME}-backend -n ${K8S_NAMESPACE} --timeout=180s
              kubectl rollout status deploy/${APP_NAME}-frontend -n ${K8S_NAMESPACE} --timeout=180s
            '''
          }
        }
      }
    }
  }

  post {
    always {
      sh 'docker compose down -v || true'
    }
  }
}
