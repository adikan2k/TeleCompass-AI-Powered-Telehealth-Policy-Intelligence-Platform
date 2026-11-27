-- Which version of the extraction instructions a run used, so runs can be compared.
-- Runs made before this column existed used the first version.

ALTER TABLE extraction_run ADD COLUMN prompt_version text NOT NULL DEFAULT 'v1';
