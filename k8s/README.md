# HORIZON GRID -- Kubernetes manifests

Plain-YAML, kustomize-compatible manifests under `k8s/base/` -- a direct
translation of `docker-compose.yml` (postgres, redis, neo4j, opensearch,
backend, celery_worker, celery_beat, frontend) into Kubernetes objects. No
Helm, no templating magic: every file is a normal manifest you can read
top to bottom.

## Layout

```
k8s/base/
  namespace.yaml                    # ioc-intel-platform namespace
  configmap.yaml                    # non-secret config (hosts, ports, URLs)
  secret.example.yaml               # placeholder only -- NOT applied, NOT referenced by kustomization.yaml
  postgres-statefulset.yaml         # + headless Service + PVC (via volumeClaimTemplates)
  redis-deployment.yaml             # + Service
  neo4j-statefulset.yaml            # + headless Service + PVC
  opensearch-statefulset.yaml       # + headless Service + PVC
  backend-deployment.yaml           # + Service, /health probes, resources
  celery-worker-deployment.yaml     # same image as backend, runs the Celery worker
  celery-beat-deployment.yaml       # same image as backend, runs Celery beat (1 replica, singleton)
  frontend-deployment.yaml          # + Service
  ingress.yaml                      # /api -> backend, / -> frontend
  kustomization.yaml                # ties it all together
```

## Config vs. secrets

- `configmap.yaml` holds everything non-sensitive: service hostnames/ports
  (`POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`), broker/cache URLs
  (`REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`), `NEO4J_URI`,
  `OPENSEARCH_URL`, and the Bedrock model/region settings.
- The Secret (`ioc-intel-secrets`) holds everything with a credential in it:
  `DATABASE_URL` (embeds the postgres password), `POSTGRES_PASSWORD`,
  `NEO4J_PASSWORD`, `JWT_SECRET_KEY`, AWS keys, and every provider API key
  from `.env.example` (VirusTotal, AbuseIPDB, OTX, NVD, abuse.ch, and the
  paid/stub providers).
- `backend`, `celery-worker`, and `celery-beat` all consume both via
  `envFrom` (a `configMapRef` + a `secretRef`), exactly mirroring how
  docker-compose merges `environment:` and `env_file: .env`.

## Creating the real Secret

`secret.example.yaml` is a placeholder with empty string values -- it exists
purely to document which keys the real Secret must have. It is intentionally
**not** listed in `kustomization.yaml`'s `resources:`, so it never gets
applied by accident and it's safe to commit.

To create the actual `ioc-intel-secrets` Secret from your local `.env` file
(the same one docker-compose reads via `env_file: .env`):

```bash
kubectl create namespace ioc-intel-platform --dry-run=client -o yaml | kubectl apply -f -

kubectl create secret generic ioc-intel-secrets \
  --namespace ioc-intel-platform \
  --from-env-file=.env
```

Make sure your `.env` also includes `POSTGRES_USER`, `POSTGRES_PASSWORD`,
`DATABASE_URL`, `NEO4J_USER`, and `NEO4J_PASSWORD` (docker-compose sets these
as service-level `environment:` on `postgres`/`neo4j`/`backend` rather than
via `.env`, so they may not already be in your `.env.example`-derived file --
add them before running the command above). See `secret.example.yaml` for
the full list of keys expected.

If you'd rather hand-edit a manifest instead of using `--from-env-file`, copy
`secret.example.yaml`, fill in real values, and `kubectl apply -f` it
directly (do not add it back into `kustomization.yaml`, and do not commit the
filled-in copy).

## Applying

```bash
# 1. Create the namespace + real secret first (see above), then:
kubectl apply -k k8s/base

# check rollout
kubectl -n ioc-intel-platform get pods
kubectl -n ioc-intel-platform rollout status deployment/backend
```

To preview the rendered manifests without applying:

```bash
kubectl kustomize k8s/base
```

## Notes / things to adjust before using this for real

- **Images**: `backend-deployment.yaml`, `celery-worker-deployment.yaml`,
  `celery-beat-deployment.yaml`, and `frontend-deployment.yaml` reference
  `ioc-intel-platform/backend:latest` and `ioc-intel-platform/frontend:latest`.
  Build and push these from `backend/Dockerfile` and a `frontend/Dockerfile`
  (production build: `npm run build && npm start`, not the docker-compose dev
  command) to a registry your cluster can pull from, then update the image
  references (and pin a real tag instead of `latest`).
- **Ingress**: `ingress.yaml` uses the legacy
  `kubernetes.io/ingress.class: "nginx"` annotation and a placeholder host
  (`ioc-intel.example.com`). Update the host, and switch to
  `spec.ingressClassName: nginx` if your ingress-nginx version expects that
  instead of the annotation.
- **TLS**: intentionally commented out in `ingress.yaml`. Fill in a real
  `tls:` block plus a cert-manager `ClusterIssuer` annotation
  (`cert-manager.io/cluster-issuer: ...`) before exposing this outside a
  trusted network.
- **Storage**: PVC sizes in the StatefulSets (postgres 5Gi, neo4j 5Gi,
  opensearch 10Gi) are starting points -- size them for your data volume, and
  set `storageClassName` if your cluster's default isn't what you want.
