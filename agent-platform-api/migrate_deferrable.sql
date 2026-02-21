
-- Drop old constraint

ALTER TABLE agent_spans
  DROP CONSTRAINT IF EXISTS agent_spans_parent_span_id_fkey;

-- Add DEFERRABLE constraint
ALTER TABLE agent_spans
  ADD CONSTRAINT agent_spans_parent_span_id_fkey
  FOREIGN KEY (parent_span_id)
  REFERENCES agent_spans(span_id)
  DEFERRABLE INITIALLY DEFERRED;
