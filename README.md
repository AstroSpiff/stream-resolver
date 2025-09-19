# Stream Resolver

Stream Resolver is a FastAPI application designed to manage and resolve streaming links. It provides a flexible way to import playlists into a database, orchestrate resolvers, and build Xtream-compatible packages, with an administrative interface for management.

## Prerequisites

Before you begin, ensure you have the following installed:

*   [Docker](https://docs.docker.com/get-docker/)
*   [Docker Compose](https://docs.docker.com/compose/install/)

## Getting Started

To get the application up and running, follow these steps:

1. **Clone the repository**

   ```bash
   git clone <repository-url>
   cd stream-resolver
   ```

2. **Prepare the local folders** (so Docker does not create them as root)

   ```bash
   mkdir -p config/db-data config/resolvers resolvers
   ```

   * `config/` stores the application settings, Xtream cache and other runtime files.
   * `config/db-data/` persists the embedded PostgreSQL data directory.
   * `resolvers/` (optional) can host custom Python resolvers that are mounted read-only inside the container.

3. **Build and start the stack**

   ```bash
   docker compose up --build -d
   ```

   The first run downloads the base images, builds the application layer and initialises the database. Subsequent runs can omit `--build`.

4. **Verify the services**

   ```bash
   docker compose ps
   docker compose logs -f resolver
   ```

   When the resolver service reports `Application startup complete`, the admin UI is available at `http://localhost:8791/static/admin/index.html` and the API docs at `http://localhost:8791/docs`.

## Configuration

The application's configuration is managed through volume mounts in the `docker-compose.yml` file. You can modify the following directories to configure the application:

*   `./config/settings.json`: Created automatically at first run; stores global settings saved from the admin UI.
*   `./config/resolvers`: Populated by the UI with resolver presets you create.
*   `./config/xtream_cache`: Cache directory for Xtream builds.
*   `./config/db-data`: PostgreSQL data files (mounted into the `db` service).
*   `./resolvers`: Optional external Python resolvers that are mounted read-only at `/opt/external-resolvers`.

## Usage

### Admin Interface

The administrative interface is available at `http://localhost:8791/static/admin/index.html`. From here, you can:

- import playlists that are then stored in the database and refreshed automatically,
- configure resolvers and MediaFlow proxies,
- assemble Xtream packages without generating `.m3u` files on disk.

### API

The application provides a set of API endpoints for interacting with the streaming services. You can explore the available endpoints and their documentation at `http://localhost:8791/docs`.

### Docker services

- `resolver`: FastAPI application exposed on port `8791`. It honours the `DATABASE_URL`, `TZ` and `RESOLVERS_DIR` environment variables defined in `docker-compose.yml`.
- `db`: PostgreSQL 16 initialised with the database `streamresolver` and credentials `resolver` / `resolver`, exposed on host port `5433` for debugging or external tools.
