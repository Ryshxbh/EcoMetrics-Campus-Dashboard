# Run EcoMetrics from published container images

This small bundle runs the published EcoMetrics services; it does not contain the application source. The images must first be published to GHCR by the project owner, and both application packages must be public for anonymous downloads.

## Windows PowerShell

1. Install and start Docker Desktop, then wait until its engine is running.
2. Copy `.env.published.example` to `.env` and open `.env` in Notepad.
3. Set `GHCR_OWNER` to the lowercase GitHub username or organization that owns the images. Replace `POSTGRES_PASSWORD` with a strong local password.
4. In PowerShell in this folder, run:

   ```powershell
   docker compose -f compose.published.yaml up -d --pull always
   ```

5. Open `http://localhost:8080`.

Stop the app but keep its data with `docker compose -f compose.published.yaml down`.

## Linux shell

Copy `.env.published.example` to `.env`, edit `GHCR_OWNER` and `POSTGRES_PASSWORD`, then run:

```sh
docker compose -f compose.published.yaml up -d --pull always
```

Open `http://localhost:8080`. Stop the app while preserving data with:

```sh
docker compose -f compose.published.yaml down
```

## Receive new updates

When the maintainer publishes a newer image, upgrade with:

```sh
docker compose -f compose.published.yaml pull
docker compose -f compose.published.yaml up -d
```

The compose file checks for new images whenever it is started. It does not restart a running installation automatically when the registry changes.
