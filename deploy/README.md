# Local service operations

This guide describes the reference single-host deployment: Ubuntu 24.04, PostgreSQL 16, system Python 3.12, and systemd. The scripts locate the source checkout from their own path. The running service uses a root-owned wheel installation under `/opt/pgfacade`; it does not import the editable checkout.

| Location | Purpose |
|---|---|
| `http://127.0.0.1:8765` | Local REST API |
| `/opt/pgfacade/.venv` | Symlink to the active versioned environment |
| `/opt/pgfacade/releases` | Preserved environments, wheels, manifests, and previous units |
| `/opt/pgfacade/release-info.txt` | Active release fingerprint and predecessor |
| `/etc/pgfacade/service.conf` | Nonsecret runtime configuration, root-owned mode 0600 |
| `/etc/pgfacade/keys.json` | Per-client principals and keys, root-owned mode 0600 |
| `/var/lib/pgfacade` | Service-owned state, mode 0700 |
| `/var/lib/postgresql/16/main` | PostgreSQL data, owned by postgres, mode 0700 |
| `/var/backups/pgfacade` | Encrypted daily backups, root-only |

The `pgfacade` OS account has no login shell. systemd supplies API keys through `LoadCredential`. The service cannot modify its code, read home directories, or read the host key file or backup private key. PostgreSQL accepts Unix-socket peer authentication only. The connector can connect only to the `pgfacade` database and switch only to its reader and writer roles.

## Adapt it to another host

Host-specific values are named constants at the top of each file. Change them there:

| File | Constants |
|---|---|
| [update](update) | `APP_ROOT`, `UNIT_PATH`, `SYSTEM_PYTHON`, `API_PORT` |
| [check-host](check-host) | `APP_ROOT`, `BACKUP_DIRECTORY`, `API_PORT`, `SYSTEM_PYTHON`, `POSTGRES_UNIT`, `DATABASE`, `DATABASE_DIRECTORY` |
| [test](test) | `SYSTEM_PYTHON`, `SOCKET_DIRECTORY` |
| [pgfacade-backup](pgfacade-backup) | `BACKUP_DIRECTORY`, `PUBLIC_CERTIFICATE`, `RETAINED_DAYS`, `SOCKET_DIRECTORY`, `DATABASE` |
| [check-service.py](check-service.py) | `BASE_URL`, `KEY_FILE` |

The unit files state the same values literally: the PostgreSQL unit name in `After=`, `Requires=`, and `PartOf=`, and the install path and port in `ExecStart=` of [pgfacade.service](pgfacade.service). The role and database names in [provision.sql](provision.sql) and in the policy query of `check-host` are `pgfacade`, `pgfacade_owner`, `pgfacade_reader`, and `pgfacade_writer`.

## Check the installation

From the checkout:

```sh
sudo bash deploy/check-host
systemctl status pgfacade.service --no-pager
sudo journalctl -u pgfacade.service -n 30 --no-pager
```

[check-host](check-host) checks each service, listener ownership, sandbox settings, installed unit, code ownership, credential metadata, PostgreSQL policy, backup freshness, and disk reserve. It then runs [check-service.py](check-service.py) with protected keys in memory. The API checker disables proxy routing and redirects, verifies each named client's role, and tests denied operations without changing application data. Its checks remain active under optimized Python.

`/healthz` is public local liveness metadata. For authenticated readiness, send `{"kind":"server.health","input":{}}` to `/call` or POST `/server/health`.

## Read the database from a local MCP session

[operator.sql](operator.sql) adds an optional `pgfacade_operator` login. It inherits `pgfacade_reader`, has no password, defaults to read-only transactions, and can connect only to the `pgfacade` database. One OS account is mapped to it through peer authentication. `check-host` accepts this login and rejects any other attribute, membership, or database on it.

```sh
sudo -u postgres psql -X -f deploy/operator.sql
echo "operator $USER pgfacade_operator" | sudo tee -a /etc/postgresql/16/main/pg_ident.conf
echo 'local pgfacade pgfacade_operator peer map=operator' | sudo tee -a /etc/postgresql/16/main/pg_hba.conf
sudo systemctl reload postgresql@16-main.service
sudo bash deploy/check-host
```

Connect with `PGFACADE_DSN='postgresql://pgfacade_operator@/pgfacade?host=/var/run/postgresql'` and `PGFACADE_READ_ONLY=true`.

## Use the API

Provision a unique key for each application or person. Map ordinary clients to `pgfacade_reader` with `read_only=true`, or to `pgfacade_writer` for row changes. Leave SQL, DDL, admin, migration, and notification flags false. The reader/writer bootstrap keys are administrative verification credentials; do not distribute one shared writer key to every application.

An operator must deliver a client's key through the application's secret store or a protected file owned by that application. A curl configuration file has this format, with the placeholder replaced in a trusted local editor:

```text
header = "Authorization: Bearer REPLACE_WITH_THE_CLIENT_KEY"
```

Set its mode to 0600. Never put an actual key in command arguments, shell history, source control, tickets, or chat. Do not use verbose HTTP logging with credentials.

```sh
curl --disable --noproxy '*' --config /path/to/client.curl \
    --json '{"kind":"server.whoami","input":{}}' http://127.0.0.1:8765/call
curl --disable --noproxy '*' --config /path/to/client.curl \
    http://127.0.0.1:8765/ops
```

Use a trusted local terminal to manage `/etc/pgfacade/keys.json`. To revoke or replace a key, update that protected mapping and restart `pgfacade.service`; no database-role change is needed for key rotation. Keep the file nonempty and retain reader/writer verification principals. Missing or invalid configuration fails startup.

For access from another machine, forward the facade through SSH:

```sh
ssh -N -L 127.0.0.1:8765:127.0.0.1:8765 your-user@your-server
```

Connect to your machine's `127.0.0.1:8765` and still provide the API key. Do not open PostgreSQL or the facade to the public network. Direct PostgreSQL TCP connections and database TCP tunnels are disabled.

## Create application tables

Runtime keys cannot create tables. Apply reviewed schema changes through the PostgreSQL administrator, switching to the non-login owner so default grants apply:

```sh
sudo -u postgres psql -X --set=ON_ERROR_STOP=on --dbname=pgfacade
```

```sql
SET ROLE pgfacade_owner;
CREATE TABLE app.notes (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    body text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
```

The reader receives SELECT; the writer receives SELECT/INSERT/UPDATE/DELETE and sequence privileges. Imported objects or objects created by another owner need an explicit grant review. The one-time [provision.sql](provision.sql) creates the database and roles; do not rerun it during updates.

```sh
curl --disable --noproxy '*' --config /path/to/writer.curl \
    --json '{"kind":"rows.insert","input":{"table":"app.notes","rows":[{"body":"First note"}]}}' \
    http://127.0.0.1:8765/call
curl --disable --noproxy '*' --config /path/to/reader.curl \
    --json '{"kind":"rows.select","input":{"table":"app.notes","limit":20}}' \
    http://127.0.0.1:8765/call
```

## Test and update

Run as the checkout owner:

```sh
./deploy/test && ./deploy/update
```

[test](test) uses a unique disposable database and a source snapshot accessible only to its owner and the PostgreSQL group. It runs the full Python suite without putting test credentials in files or pointing tests at the live database.

[update](update) snapshots reviewed source and the lockfile, runs lint and database-independent tests, builds an uneditable wheel, installs hash-verified dependencies into a new root-owned release, and takes an encrypted backup. It serializes deployments, preserves the previous environment/unit/manifest, switches the service, and runs host/API checks. Failed activation restores the predecessor. It does not modify Git, credentials, or application schemas. Interrupted or failed releases are retained for inspection.

The updater requires the current symlink-based release layout, `uv`, system Python 3.12, local PostgreSQL, and noninteractive sudo. Pull, merge, and review source changes separately. The active package and source fingerprint come from `release-info.txt`.

For a manual rollback, first save the current release directory (the parent of the resolved `.venv` target). Read its `release-info.txt` for `previous_release`. Stop the facade and replace `.venv` atomically with a symlink to that predecessor environment. Restore `previous.service` and `previous-info.txt` from the saved current release directory to the installed unit and active manifest, reload systemd, and start the facade. These files belong to the release being rolled back; do not use the predecessor's own `previous.*` files. Run `check-host` and the API checks for that version. Database schema changes require their own migration/recovery plan.

## Backups and recovery

[pgfacade-backup.timer](pgfacade-backup.timer) runs around 03:30 local time and catches up after downtime. The [backup program](pgfacade-backup) streams a PostgreSQL custom-format dump into OpenSSL CMS AES-256-GCM encryption, publishes atomically, and retains seven daily files. It never writes a plaintext dump to disk. Manual runs replace the same day's archive.

```sh
sudo systemctl start pgfacade-backup.service
systemctl list-timers pgfacade-backup.timer
sudo journalctl -u pgfacade-backup.service -n 20 --no-pager
```

Encryption uses `/etc/pgfacade/backup-public.pem`; the root-only decryption key is `/etc/pgfacade/backup-private.pem`. The backup service cannot read that private key or the API key file. Never overwrite or regenerate an existing recovery key. Keep a separate controlled recovery-key copy; retain old keys when rotating them.

Restore only a trusted archive. Fully decrypt and authenticate it into a root-only temporary directory on `/run`, wait for success, then restore into a new scratch database. Do not pipe decryption directly into `pg_restore`, because plaintext can appear before the final authentication tag is checked.

In a root shell, select the archive explicitly:

```sh
set -euo pipefail
umask 077
restore_directory=$(mktemp -d /run/pgfacade-restore.XXXXXX)
trap 'rm -rf -- "$restore_directory"' EXIT
openssl cms -decrypt -binary -inform DER \
    -in /var/backups/pgfacade/pgfacade-YYYY-MM-DD.dump.cms \
    -inkey /etc/pgfacade/backup-private.pem \
    -recip /etc/pgfacade/backup-public.pem \
    -out "$restore_directory/database.dump"
runuser -u postgres -- createdb pgfacade_restorecheck
runuser -u postgres -- pg_restore --dbname=pgfacade_restorecheck \
    --exit-on-error --single-transaction < "$restore_directory/database.dump"
```

Inspect the restored data, owner and grants, then explicitly drop only the scratch database. The owner/runtime roles must already exist. On a new server, recreate roles first and restore into a fresh database; reapply database CONNECT restrictions and separately protected service configuration. `/run` needs enough free space for the decrypted archive. Encryption verifies integrity, not the creator's identity.

## Open operational requirements

Off-server encrypted copies, separately stored recovery keys, and external backup-failure alerts still need an operator-selected destination. Local backups do not cover loss or compromise of this server and do not provide point-in-time recovery.

`check-host` warns at 90% database filesystem usage and rejects less than 10 GiB free. This is a deployment check, not continuous alert delivery or a hard database storage quota. Monitor growth, backup age, service restarts and failed units. See the [security verification record](SECURITY.md) for scope and residual trust assumptions.
