-- One-time setup: run this in pgAdmin as your Postgres superuser.
-- Creates a dedicated database + app login for this project, scoped to just
-- this database — not your personal superuser account.
--
-- After running this, put the password you choose below into .env
-- (see .env.example at the repo root) as PG_PASSWORD.

CREATE ROLE aiplaybook_app WITH LOGIN PASSWORD 'CHANGE_ME';

CREATE DATABASE aiplaybook OWNER aiplaybook_app;

-- Connect to the new "aiplaybook" database before running schema.sql
-- (in pgAdmin: right-click aiplaybook -> Query Tool).
