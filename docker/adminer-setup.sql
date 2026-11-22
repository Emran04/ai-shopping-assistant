\getenv adminer_password ADMINER_PASSWORD

SELECT format('CREATE ROLE admin LOGIN PASSWORD %L', :'adminer_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'admin')
\gexec

GRANT USAGE ON SCHEMA public TO admin;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO admin;
GRANT INSERT ON TABLE public.products TO admin;
GRANT USAGE ON SEQUENCE public.products_id_seq TO admin;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO admin;
