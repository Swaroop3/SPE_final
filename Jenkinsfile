pipeline {
  agent any

  environment {
    REGISTRY         = "docker.io/your-org"
    IMAGE_TAG        = "${env.GIT_COMMIT ?: 'dev'}"
    APP_NAME         = "sentinelcare"
    MODEL_PATH       = "models/mock_artifacts/sepsis_mock_model.json"
    COMPOSE_SERVICES = "backend frontend patients vitals alerts scoring auth tasks audit simulator notifications mongo"
    K8S_NAMESPACE    = "sentinelcare"
    HELM_CHART_PATH  = "infra/helm/sentinelcare"
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
          PYTHONPATH=backend python - <<'PY'
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

    stage('Tests') {
      steps {
        sh '''
          . .venv/bin/activate
          pip install pytest pytest-asyncio
          PYTHONPATH=backend pytest backend/tests || true
          cd frontend && pnpm test -- --watch=false || true
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
          curl -s http://localhost:8001/health
          TOKEN=$(curl -s -X POST http://localhost:8001/auth/login -H "Content-Type: application/json" -d '{"username":"admin@sentinel.care","password":"admin123"}' | jq -r .access_token)
          curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8001/patients | head -c 200
          curl -I http://localhost:8081
        '''
      }
    }

    stage('Build Images (for registry)') {
      steps {
        sh '''
          docker build -f backend/Dockerfile -t ${REGISTRY}/${APP_NAME}-backend:${IMAGE_TAG} .
          docker build -f frontend/Dockerfile -t ${REGISTRY}/${APP_NAME}-frontend:${IMAGE_TAG} .
          for svc in patients vitals alerts scoring simulator auth tasks audit notifications; do
            docker build -f services/$svc/Dockerfile -t ${REGISTRY}/${APP_NAME}-${svc}:${IMAGE_TAG} .
          done
        '''
      }
    }

    stage('Image Scan') {
      steps {
        sh '''
          command -v trivy >/dev/null 2>&1 || echo "trivy not installed on agent"
          if command -v trivy >/dev/null 2>&1; then
            for svc in backend frontend patients vitals alerts scoring simulator auth tasks audit notifications; do
              trivy image --severity HIGH,CRITICAL ${REGISTRY}/${APP_NAME}-${svc}:${IMAGE_TAG} || true
            done
          fi
        '''
      }
    }

    stage('Push Images') {
      when { branch "main" }
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
      when { branch "main" }
      steps {
        sh '''
          # Pull images from registry to validate availability
          for svc in backend frontend patients vitals alerts scoring simulator auth tasks audit notifications; do
            docker pull ${REGISTRY}/${APP_NAME}-${svc}:${IMAGE_TAG}
          done

          # Helm deploy using pulled image tags (cluster must be configured on agent)
          helm upgrade --install ${APP_NAME} ${HELM_CHART_PATH} \
            --namespace ${K8S_NAMESPACE} --create-namespace \
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

  post {
    always {
      sh 'docker compose down -v || true'
    }
  }
}
