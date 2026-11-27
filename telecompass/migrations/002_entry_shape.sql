-- Columns found to be needed once the real page was read:
--   a topic can have sub-headings, a SOURCE line can link to more than one document,
--   and the "At a Glance" panel is split into named groups.

ALTER TABLE entry ADD COLUMN subtopic text;
ALTER TABLE entry ADD COLUMN source_links jsonb NOT NULL DEFAULT '[]';

ALTER TABLE glance_answer ADD COLUMN section text NOT NULL DEFAULT '';
