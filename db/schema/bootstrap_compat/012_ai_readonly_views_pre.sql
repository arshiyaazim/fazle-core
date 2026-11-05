-- Fresh-database prerequisite for AI read-only views.
--
-- Production provisions this cluster role outside table migrations. A new
-- self-contained database cluster has no such role, while migrations 012, 045
-- and 063 grant views to it. Create a safe NOLOGIN group role; operators may
-- later grant it to a separately authenticated runtime user.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fazle_ai_reader') THEN
        CREATE ROLE fazle_ai_reader NOLOGIN
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION;
    END IF;
END $$;
