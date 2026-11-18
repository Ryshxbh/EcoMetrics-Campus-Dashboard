# Publish and run EcoMetrics

EcoMetrics is a three-container application (web, API, PostgreSQL). A Dockerfile builds an application image; Compose describes how those images work together. To let someone run the dashboard without cloning the source or building images, publish the API and web images to GitHub Container Registry (GHCR), then share `compose.published.yaml` and the setup steps below.

## Publish from GitHub

1. Create a GitHub repository for this project and push the project source to its `main` branch. Do not add `.env`; it contains machine-local database credentials and is ignored by Git.
2. In the repository, open **Actions** and confirm that **Publish images** is enabled. A push to `main` builds and publishes the API and web images. A version tag such as `v1.0.0` publishes the same release tag. CI builds both images for pull requests and pushes to `main`.
3. After the first successful publish, open the repository owner's **Packages** page. For both `ecometrics-api` and `ecometrics-web`, open **Package settings**. Since the source repository can remain private while images are shared, disable inherited repository access for each package if GitHub enabled it, then set package visibility to **Public**. Public GHCR packages can be pulled anonymously. GitHub warns that a package made public cannot be made private again.
4. Share `compose.published.yaml` and `.env.published.example` with recipients. Do not send your personal `.env` file.

The workflow publishes mutable `main` tags for the latest successful `main` build and immutable full-commit tags (`sha-<40-character-commit-sha>`) for traceability and repeatable deployment. For a reproducible Compose deployment, set `IMAGE_TAG` to a release tag such as `v1.0.0` or to the full `sha-...` tag instead of `main`.

## Run from published images

Prerequisite: Docker Engine with Docker Compose v2, or Docker Desktop with its container engine running.

1. Put `compose.published.yaml` and `.env.published.example` in one folder.
2. Copy `.env.published.example` to `.env`.
3. Edit `.env`: set `GHCR_OWNER` to the lowercase GitHub username or organization that owns the images, and replace `POSTGRES_PASSWORD` with a strong local password.
4. Start the application:

   ```sh
   docker compose -f compose.published.yaml up -d --pull always
   ```

5. Open `http://localhost:8080`. Check service status with:

   ```sh
   docker compose -f compose.published.yaml ps
   docker compose -f compose.published.yaml logs -f api
   ```

The database is stored in the named `ecometrics-postgres-data` volume. `docker compose -f compose.published.yaml down` stops the stack but keeps its data. Add `-v` only when you intentionally want to delete the database and its contents.

## Upgrade to a newer build

The published Compose file uses `pull_policy: always`: each `up` checks the registry for the current image tag. After a new image is published, upgrade a running installation with:

```sh
docker compose -f compose.published.yaml pull
docker compose -f compose.published.yaml up -d
```

Publishing is continuous on pushes to `main`; a Compose installation is updated when its operator runs the upgrade command (or schedules it in their own operations system). The OpenShift workflow can perform a cluster rollout when configured with cluster credentials. No host automatically changes a running container merely because a registry tag moved.

## Hosted deployment

The repository includes OpenShift manifests and a GitHub Actions deployment workflow. After an image publish succeeds from `main`, the workflow automatically rolls out the matching immutable full-commit image tags if `OPENSHIFT_SERVER`, `OPENSHIFT_TOKEN`, and `OPENSHIFT_NAMESPACE` are configured. Without those secrets it records a skip, so image publication still succeeds. Manual version-tag rollouts remain available through **Deploy to OpenShift**. A live internet URL also requires an OpenShift cluster and a database credential Secret in that namespace. See [DEPLOYMENT.md](DEPLOYMENT.md). Publishing images alone creates runnable artifacts; it does not provide an always-on host.
