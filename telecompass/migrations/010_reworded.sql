-- An entry whose wording changed but whose substance did not (punctuation, an added "the").
ALTER TABLE entry_change DROP CONSTRAINT entry_change_kind_check;
ALTER TABLE entry_change ADD CONSTRAINT entry_change_kind_check
    CHECK (kind IN ('added', 'removed', 'changed', 'reworded', 'rechecked'));
