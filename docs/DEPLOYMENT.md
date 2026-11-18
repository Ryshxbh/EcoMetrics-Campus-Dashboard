# Run and deploy

## Docker Compose

From the repository root, create a local `.env` file and change the password before starting the services:

```sh
cp .env.example .env
docker compose up --build -d
docker compose ps
```

Open `http://localhost:8080`. Nginx is the only published service. For service logs and common inspection commands:

```sh
docker compose logs -f api
docker compose logs -f db
docker compose exec api id
docker compose exec api python -c "import os; print(os.getuid())"
docker network ls
docker volume ls
```

### Windows Docker Desktop build recovery

If Docker Desktop reports a read-only containerd database or `exec /bin/sh: accessing a corrupted shared library`, save any work in WSL and run `wsl --shutdown` from PowerShell. This stops all WSL distributions. Start Docker Desktop again. On the project machine, an isolated BuildKit builder named `ecometrics-recovery` is configured; rebuild both images with:

```sh
docker compose --env-file .env build --builder ecometrics-recovery
docker compose --env-file .env up --detach --no-build
```

The project-specific API image uses numeric UID `10001` and group `0`; it does not need a named user or root privileges in the image.

Use `docker compose down` to stop while preserving the database, or `docker compose down -v` to remove the named database volume and reseed on the next start. Do not use the `-v` form if you need the stored database.

## Podman on Linux

Podman can build the same OCI-compatible API image without a continuously running central daemon:

```sh
podman build -t ecometrics-api:local -f Dockerfile .
podman images
podman inspect ecometrics-api:local
podman run --rm --entrypoint python ecometrics-api:local --version
```

To run the complete stack under Podman, use a compatible Compose provider (`podman compose` delegates to an installed provider). Compose provider availability and support for security/resource options vary by host. The viva guide gives the concepts and comparison to Docker Engine.

## Publish to GitHub Container Registry

See [PUBLISHING.md](PUBLISHING.md) for the end-to-end first-time publishing guide and for running the images from Compose. The `Build containers` workflow builds images on pull requests and `main`. The `Publish images` workflow publishes `ghcr.io/<owner>/ecometrics-api:main` and `ghcr.io/<owner>/ecometrics-web:main`, plus immutable full-commit tags in the form `sha-<40-character-commit-sha>`; a pushed version tag such as `v1.0.0` publishes that release tag too. BuildKit layer caches are enabled.

In GHCR, choose package visibility to match the intended audience. Public packages allow anonymous pulls. If packages remain private, configure an image pull secret in the target OpenShift namespace.

## First OpenShift deployment

These manifests require an OpenShift project/namespace with a default StorageClass that can provision a 2 GiB `ReadWriteOnce` claim.

1. Replace `ghcr.io/YOUR-ORG` in `openshift/api.yaml` and `openshift/web.yaml` with the GitHub organization or username that owns the published packages.
2. Log in to the cluster and select the project:

   ```sh
   oc login https://YOUR-OPENSHIFT-API:6443
   oc project YOUR-NAMESPACE
   ```

3. Create the database credentials as a cluster Secret. Use strong, different values:

   ```sh
   oc create secret generic ecometrics-db-credentials --from-literal='password=CHOOSE-A-LONG-DATABASE-PASSWORD' --from-literal='admin-password=CHOOSE-A-DIFFERENT-ADMIN-PASSWORD'
   ```

4. Apply the configuration and workloads:

   ```sh
   oc apply -f openshift/config.yaml
   oc apply -f openshift/database.yaml
   oc apply -f openshift/api.yaml
   oc apply -f openshift/web.yaml
   oc apply -f openshift/route.yaml
   oc get pods,svc,pvc,route
   ```

5. Wait for the database and API readiness probes to pass, then open the host shown by `oc get route ecometrics`.

For automatic rollouts after a successful `main` image publish, add repository Actions secrets named `OPENSHIFT_SERVER`, `OPENSHIFT_TOKEN`, and `OPENSHIFT_NAMESPACE`. Create the database credential Secret in the cluster namespace before the first rollout. If these secrets are not configured, automatic rollout is skipped while image publishing remains successful. Each automatic rollout uses the immutable full-commit `sha-...` image tag, which changes the Deployment image reference and triggers a rollout for every published commit. To promote a version manually, run **Deploy to OpenShift** and provide the release tag published by the image workflow, such as `v1.0.0`. The workflow updates both image references and waits for rollout status.

The database is a single replica on persistent storage for this capstone. A production service would also plan database backups, restore drills, managed secrets, TLS/identity policies, network policy, database high availability, alerting, and a migration framework.
