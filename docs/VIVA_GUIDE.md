# Viva guide: EcoMetrics Campus Dashboard

## One-minute project explanation

> EcoMetrics is a containerized campus electricity dashboard. It uses the public I-BLEND meter dataset from IIIT-Delhi, converts minute-level power readings into hourly building records, and exposes three core functions: an energy and building-intensity overview, an academic-calendar operating profile, and a new Meter Trust view that exposes missingness and statistical review flags. The stack is Nginx, FastAPI, and PostgreSQL, built as Docker images and coordinated with Compose. The API loads the included dataset once into persistent PostgreSQL storage. The build workflow validates configuration and builds images, GHCR stores release images, and OpenShift manifests show how to run them with probes, Services, a PVC, and a TLS Route. The data is historical and the current grid factor is only an illustrative emissions scenario.

## Suggested live demonstration (5–7 minutes)

1. **Show the user-facing app.** Open `http://localhost:8080`. Choose a date range and a building. Show the energy trend, floor-area comparison, then the Operating profile and the Meter Trust views. Explain why the data-quality view is a distinct feature: energy totals can mislead when meter coverage is uneven.
2. **Show service health.** Run `docker compose ps` and point out three independent containers and their health status. Run `docker compose logs --tail=30 api` to show the startup/seed path.
3. **Show the container identity and API.** Run `docker compose exec api id`, then `docker compose exec api python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/api/health/ready').read().decode())"`. The application process runs as a non-root UID; the health endpoint confirms application/data readiness.
4. **Show network and storage.** Run `docker network inspect ecometrics-data` and `docker volume inspect ecometrics-postgres-data`. Explain the API/database network is internal and the DB does not publish a host port; PostgreSQL state lives in a named volume.
5. **Show image construction.** Run `docker image ls ecometrics/api:local` and open the root Dockerfile. Describe the dependency stage, virtual environment, runtime stage, non-root user, and health check.
6. **Show lifecycle/recovery.** Run `docker compose restart api`, then `docker compose ps`. Explain readiness vs liveness. If needed, view `docker compose logs api` before restarting.
7. **Show delivery artifacts.** Open `.github/workflows/ci.yml`, `publish.yml`, and `deploy-openshift.yml`, then `openshift/api.yaml`. Explain build, publish, and manual rollout as separate stages; point to the probes, Services, persistent claim, and Route.

If this Windows Docker Desktop installation again shows a read-only metadata database or a corrupted shared-library error during build, use the `ecometrics-recovery` BuildKit builder described in `docs/DEPLOYMENT.md`. The dashboard is already running after the recovery, so you can use `docker compose ps` for the demonstration.

Avoid `docker compose down -v` during a demo if you want to keep the initialized database. Normal `docker compose down` preserves it.

## Dockerfile and image vocabulary

### Dockerfile instructions used here

- `FROM`: selects the base image and starts a stage. The API uses `python:3.12-slim` twice, once for dependencies and once for the final runtime.
- `WORKDIR`: sets the image's working directory.
- `COPY`: copies requirements, application code, and compact data into the appropriate stage.
- `RUN`: creates the virtual environment, installs dependencies, and prepares the runtime user/permissions.
- `ENV`: declares runtime configuration such as `PATH`, `PYTHONPATH`, and `DATA_DIR`.
- `USER`: runs the application as a non-root UID.
- `EXPOSE`: documents the API's listening port; it does not publish the port to the host.
- `HEALTHCHECK`: lets Docker report whether the application responds to its liveness endpoint.
- `CMD`: supplies the default process (`uvicorn`) for the container.

### Common questions

**What is an image?** A versioned, read-only template composed of filesystem layers and metadata. It is built from the Dockerfile and can be stored in a registry.

**What is a container?** An isolated runtime instance of an image, with a writable container layer, namespaces, cgroups, networking, and a process lifecycle managed by the runtime.

**Why use a multi-stage build?** Build-only files and caches stay out of the final image. This keeps the runtime smaller and reduces its attack surface.

**What are layers and build cache?** Instructions such as `COPY` and `RUN` create reusable image layers. If an earlier input is unchanged, the builder can reuse its cached layer. Copying `requirements.txt` before app code helps dependency installs stay cached when only source files change.

**What does `EXPOSE` do?** It documents an intended container port. Publishing it requires a runtime setting such as Compose `ports`; here only the web service publishes port 8080.

**Why not run as root?** A compromised process has fewer privileges when it is not UID 0. The app also drops capabilities, disallows privilege escalation, and has a read-only root filesystem.

**What is a volume?** Persistent storage mounted into a container. The named PostgreSQL volume outlives the replaceable database container.

**Why are there two networks?** `edge` accepts host traffic at Nginx. `data` is an internal network for proxy-to-API and API-to-database traffic. The database is not directly exposed to the host.

**What is the difference between liveness and readiness?** Liveness says the process should keep running; readiness says it can serve requests. The API readiness endpoint checks that its database contains readings.

## Linux and container commands to explain

| Command | What to say |
| --- | --- |
| `docker compose ps` | Lists service containers and their state/health. |
| `docker compose logs -f api` | Follows API logs; useful for startup/database connection issues. |
| `docker compose exec api id` | Shows the UID/GID of a process inside the running container. |
| `docker compose exec api sh` | Opens a shell for inspection, if the image includes one. |
| `docker inspect <container>` | Shows image, environment, health, mounts, and network settings. |
| `docker network inspect ecometrics-data` | Shows network membership and IP details. |
| `docker volume inspect ecometrics-postgres-data` | Shows persistent volume metadata and mount point. |
| `docker compose restart api` | Restarts one service without rebuilding the image. |
| `docker compose up --build -d` | Builds changed images and starts services detached. |
| `ls`, `pwd`, `cat`, `grep`, `chmod`, `id` | Basic Linux file, path, search, permission, and identity tools. |

The app images are Linux images even when Docker Desktop is controlled from Windows. A Linux host/VM provides the kernel features that implement process, mount, user, and network namespaces and cgroups.

## Docker and Podman

**How does Podman differ from Docker Engine?** Both use OCI-compatible images and can run OCI containers. Docker commonly has a long-running daemon controlled through the Docker CLI. Podman is designed to run daemonless and supports rootless operation; its CLI deliberately resembles Docker. `podman compose` commonly delegates Compose behavior to an installed provider, so compatibility depends on that provider.

**What does rootless mean?** The invoking user can build/run containers without a privileged root-owned container daemon. User namespaces map container IDs to unprivileged host IDs; some networking and storage features can differ from rootful mode.

**How can I demonstrate Podman?** On a Linux system with Podman installed, run:

```sh
podman build -t ecometrics-api:local -f Dockerfile .
podman images
podman inspect ecometrics-api:local
```

Then explain that the same OCI image can be pushed to a registry and pulled by a compatible runtime. The Compose-based full stack is demonstrated with Docker Compose in this project.

## Build, registry, upgrades, and deployment

**What happens in CI?** Pull requests and pushes to `main` validate the Compose file and build both images. The publish workflow tags images with the branch or release and commit SHA and pushes them to GHCR. BuildKit caches common layers. Dependabot proposes regular dependency, base-image, and action updates.

**Why tag an image with a commit SHA?** A commit-SHA tag identifies the source revision associated with a built artifact and supports traceability. For a production release, deploy an approved immutable digest or SHA tag rather than relying indefinitely on a moving branch tag.

**How is continuous deployment represented?** OpenShift deployment is a separate manually triggered workflow. It applies the manifests, changes Deployment image references to a selected published tag, and waits for rollouts. This is controlled promotion of the exact built images, rather than rebuilding inside the cluster.

**What does OpenShift add?** It is a Kubernetes platform with application image/build/deployment features. In these manifests, Deployments manage replicas, Services provide stable in-cluster names, a PVC requests persistent database storage, probes control health, resource limits bound usage, and a Route exposes the web service with edge TLS.

**What is an image registry?** A service that stores and distributes container images, such as GHCR. The workflow authenticates to GHCR with the repository's short-lived `GITHUB_TOKEN` and grants package-write permission.

## Data and sustainability questions

**Where did the CSV come from?** The derived dataset comes from the CC0 I-BLEND IIIT-Delhi energy archive and published academic calendar. Links and provenance are in `data/README.md`.

**Why process minute readings into hours?** Hourly summaries make campus trends easier to understand and reduce the runtime dataset from a large archive to a compact file while retaining quality coverage for each building-hour.

**Why not replace missing readings with zero?** Zero would mean a meter measured no consumption. A missing reading means there is not enough evidence; treating it as zero would understate energy and make the building look better.

**Why show coverage?** Two buildings can have apparently different totals because one meter has more missing time. Coverage helps the viewer judge whether a comparison is usable. Recorded totals can understate actual use during missing periods; EcoMetrics does not fill them with zero.

**Is the carbon value historical?** No. The dashboard applies CEA's FY 2025–26 weighted-average factor to historical 2013–2017 electricity as a current-factor scenario. It is not a historical grid mix measurement or CO₂e inventory.

**Does a high night ratio prove waste?** No. It is a prompt to compare readings with the building schedule. Dormitories, servers, safety systems, and other continuous loads may operate at night.

**Why is Meter Trust the gap-focused feature?** Energy dashboards often emphasize totals, but totals become hard to trust if meter uptime or data completeness varies. This source itself has incomplete and unequal meter coverage. EcoMetrics exposes the evidence and supports exporting flagged rows for review rather than silently filling gaps.

## Course outcome coverage

| Outcome | Demo point |
| --- | --- |
| Linux operations | Identify process UID, permissions, logs, mounted storage, and basic troubleshooting commands. |
| Podman architecture/functionality | Explain daemonless/rootless operation and OCI compatibility; demonstrate build and inspect commands on a Podman host. |
| Dockerfiles, images, registries | Walk through stages/layers, cache, runtime image, and GHCR workflow. |
| Running/networking/troubleshooting | Show three services, health checks, private network, logs, and persistence. |
| OpenShift/Kubernetes | Explain Deployment, Service, PVC, probes, resource controls, and Route. |

## Limitations to state clearly

- The source campus is IIIT-Delhi and dates are 2013–2017; the dashboard is not live institutional data.
- Building areas and meter groupings come from the research dataset descriptions. They should not be treated as a certified energy audit.
- Night-window and meter-quality thresholds are project-defined review rules. They are visible so a reviewer can challenge or tune them.
- The capstone OpenShift database runs as one pod with a PVC. A real production service needs operational backup, restoration, high availability, and access-control design.
