# NetOps Command Center

A Netmiko network automation dashboard built with Django, Celery, and Redis. It provides encrypted credential storage, inventory and group targeting, show/config command execution, reusable templates, job and command-level logging, configuration backups, and pre/post-change validation.

## Quick start

Requirements: Python 3.12+, `uv`, Docker (for Redis), and SSH reachability to your devices.

```bash
cp .env.example .env
# Set a permanent, private SECRET_KEY in .env before storing credentials.
uv sync
docker compose up -d redis
uv run python manage.py migrate
uv run python manage.py createsuperuser
```

Run the web server and worker in separate terminals:

```bash
uv run python manage.py runserver
uv run celery -A config worker --loglevel=info
```

Open `http://127.0.0.1:8000`, sign in, then create a credential, device/group, and execution. The Django admin is at `/admin/`.

For a demo or test environment without a Redis worker, set `CELERY_TASK_ALWAYS_EAGER=True`. Jobs will execute inside the web request, so this mode is not suitable for production.

## Execution behavior

- `Connectivity test` opens SSH, enters enable mode when a secret is configured, and captures the prompt.
- `Show commands` executes each non-empty line individually.
- `Configuration change` passes all command lines to Netmiko's `send_config_set`.
- `Configuration backup` defaults to `show running-config` and stores the raw response as a downloadable `.cfg` snapshot.
- Optional pre/post commands are collected with `send_command` and labeled in the result output.
- Selecting groups and individual devices produces one deduplicated set of enabled targets.

Every target gets its own `JobResult`; every command is written to `CommandLog`, including phase, output, and success state.

## Security notes

Credential passwords and enable secrets are encrypted at rest with Fernet using a key derived from `SECRET_KEY`. Changing `SECRET_KEY` after saving credentials makes existing ciphertext unreadable, so back it up securely. Use a production database, TLS, restrictive network ACLs, and a proper secrets manager for larger deployments.

## Tests

```bash
uv run python manage.py test
```
