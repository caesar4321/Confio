Clean Rebuild (Option A)
========================

Goal: Start with a clean migration history and a clean database, without corrupting the current DB or Git history.

Summary
- Create a new (empty) database (recommended: new DB name on your existing RDS instance).
- Reset local migration files for all Django apps.
- Generate fresh 0001 migrations and migrate into the new DB.
- Create a new superuser and verify /admin.
- When satisfied, commit and push the new migrations.

Steps

1) Prepare a new DB
- Option A.1 (RDS):
  - In AWS RDS, create a new database, e.g. `confio_clean` (same instance as before).
  - Update your local `.env` to point to the new DB:
    - `DB_NAME=confio_clean`
    - `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` unchanged unless credentials differ.
  - Ensure `SECRET_KEY`, `ALLOWED_HOSTS`, and required app envs are present.

2) Reset local migrations (files only)
- Run:
  - `./scripts/reset_migrations.sh`
- This removes old migration files for local apps and leaves `__init__.py` in place.

3) Generate fresh 0001 migrations
- Run:
  - `python manage.py makemigrations`
- This creates a new 0001_initial.py per app in a consistent order.

4) Apply migrations to the clean DB
- Run:
  - `python manage.py migrate`
- This creates all tables and schema fresh.

5) Create a superuser
- Run:
  - `python manage.py createsuperuser`

6) Verify locally
- Start your app and open `/admin`.
- If you rely on Nginx/Daphne locally, ensure they’re running or use `python manage.py runserver` for a quick check.
- Verify admin add pages, especially `/admin/p2p_exchange/p2poffer/add/`.

7) Commit and push
- Once everything looks good:
  - Commit the new migration files.
  - Push to Git.
  - Deploy the code to the server and point `.env` to the new clean DB (Option A) for zero-downtime switch.

Helpers
- All in one local rebuild (requires your `.env` pointing to the NEW clean DB):
  - `CONFIRM=YES ./scripts/local_rebuild.sh`
  - This does steps 2–5 (reset, makemigrations, migrate, createsuperuser prompt).

Notes
- If you need to preserve data, do not use Option A. Instead, finish reconciling the current DB state and then squash migrations.
- When switching the production app to the new DB, keep the old DB for a rollback window.

