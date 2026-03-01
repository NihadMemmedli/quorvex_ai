# Kubernetes Deployment (Phase 3)

Enterprise-scale deployment for Quorvex AI test automation with auto-scaling browser workers.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Kubernetes Cluster                                │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐│
│  │                    Browser Worker Deployment                    ││
│  │              (HPA: min=2, max=20, target CPU=70%)              ││
│  │                                                                 ││
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐             ││
│  │  │ Pod 1   │ │ Pod 2   │ │ Pod N   │ │ Pod N+1 │  ← Auto     ││
│  │  │Playwright│ │Playwright│ │Playwright│ │Playwright│   Scale   ││
│  │  └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘             ││
│  │       └───────────┴───────────┴───────────┘                    ││
│  └────────────────────────────────────────────────────────────────┘│
│                              │                                      │
│                    ┌─────────▼─────────┐                           │
│                    │  Redis            │                           │
│                    │  (Job Queue)      │                           │
│                    └─────────▲─────────┘                           │
│                              │                                      │
│  ┌───────────────────────────┼───────────────────────────────────┐│
│  │                   Backend Deployment                           ││
│  │                   (replicas: 2)                                ││
│  │                                                                 ││
│  │  - FastAPI + Orchestrator                                      ││
│  │  - No browsers (slim image: ~200MB)                            ││
│  │  - Memory: 4G (down from 24G)                                  ││
│  └────────────────────────────────────────────────────────────────┘│
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐│
│  │  Ingress Controller (nginx-ingress)                            ││
│  │  - Routes traffic to frontend/backend                           ││
│  │  - SSL termination                                              ││
│  └────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────┘
```

## Prerequisites

1. Kubernetes cluster (1.24+)
2. kubectl configured
3. Storage class for PersistentVolumeClaims
4. nginx-ingress controller (optional, for external access)

## Quick Start

### 1. Install nginx-ingress controller (optional)

```bash
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.8.2/deploy/static/provider/cloud/deploy.yaml
```

### 2. Configure secrets

```bash
# Copy secrets template
cp secrets.yaml secrets.local.yaml

# Edit with your values
vim secrets.local.yaml

# Apply secrets (do this BEFORE kustomize)
kubectl apply -f secrets.local.yaml
```

### 3. Build and push images

```bash
# From project root
docker build -t your-registry/quorvex-worker:latest -f docker/browser-worker/Dockerfile .
docker build -t your-registry/quorvex-backend-slim:latest -f docker/backend-slim/Dockerfile .
docker build -t your-registry/quorvex-frontend:latest -f web/Dockerfile web/

docker push your-registry/quorvex-worker:latest
docker push your-registry/quorvex-backend-slim:latest
docker push your-registry/quorvex-frontend:latest
```

### 4. Update kustomization.yaml with your registry

```yaml
images:
  - name: quorvex-worker
    newName: your-registry/quorvex-worker
    newTag: latest
```

### 5. Deploy

```bash
kubectl apply -k k8s/
```

### 6. Verify

```bash
# Check pods
kubectl get pods -n quorvex

# Check HPA status
kubectl get hpa -n quorvex

# Check services
kubectl get svc -n quorvex
```

## Scaling

### Manual Scaling

```bash
# Scale browser workers
kubectl scale deployment browser-workers -n quorvex --replicas=10
```

### HPA Configuration

The HPA is configured to:
- Minimum: 2 replicas
- Maximum: 20 replicas
- Scale up when CPU > 70%
- Scale down after 5 minutes of low usage

### Monitor Scaling

```bash
# Watch HPA
kubectl get hpa -n quorvex -w

# View scaling events
kubectl describe hpa browser-workers-hpa -n quorvex
```

## Storage

Persistent Volume Claims:
- `postgres-pvc`: 10Gi - Database storage
- `runs-pvc`: 50Gi - Test run artifacts
- `logs-pvc`: 10Gi - Application logs
- `specs-pvc`: 5Gi - Test specifications
- `tests-pvc`: 10Gi - Generated tests
- `test-results-pvc`: 20Gi - Playwright reports

## Resource Limits

| Component | CPU Request | CPU Limit | Memory Request | Memory Limit |
|-----------|-------------|-----------|----------------|--------------|
| Browser Worker | 1 | 2 | 1Gi | 2Gi |
| Backend | 1 | 4 | 1Gi | 4Gi |
| Frontend | 250m | 500m | 256Mi | 512Mi |
| PostgreSQL | 500m | 2 | 1Gi | 4Gi |
| Redis | 100m | 500m | 64Mi | 256Mi |

## Troubleshooting

### Pods stuck in Pending

```bash
# Check events
kubectl describe pod <pod-name> -n quorvex

# Check PVC status
kubectl get pvc -n quorvex
```

### Browser worker crashes

```bash
# Check logs
kubectl logs -l app=browser-worker -n quorvex

# Check shared memory
kubectl exec -it <pod-name> -n quorvex -- df -h /dev/shm
```

### HPA not scaling

```bash
# Check metrics server
kubectl get --raw /apis/metrics.k8s.io/v1beta1/pods

# Check HPA events
kubectl describe hpa browser-workers-hpa -n quorvex
```

## Cleanup

```bash
# Delete all resources
kubectl delete -k k8s/

# Or delete namespace (removes everything)
kubectl delete namespace quorvex
```

## Alternative: Docker Swarm

For simpler deployments without Kubernetes:

```bash
# Initialize swarm
docker swarm init

# Deploy stack
docker stack deploy -c docker-compose.swarm.yml quorvex

# Scale workers
docker service scale quorvex_browser-workers=10
```
