-- V3: Add explicit DEFAULT '' on articles columns
-- Hibernate set these Java-side; Python needs DB-side defaults
ALTER TABLE articles ALTER COLUMN title SET DEFAULT '';
ALTER TABLE articles ALTER COLUMN link SET DEFAULT '';
ALTER TABLE articles ALTER COLUMN author SET DEFAULT '';
ALTER TABLE articles ALTER COLUMN summary SET DEFAULT '';
ALTER TABLE articles ALTER COLUMN content SET DEFAULT '';
ALTER TABLE articles ALTER COLUMN image SET DEFAULT '';
