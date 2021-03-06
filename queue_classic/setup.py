def create_queue(conn, **kwargs):
    conn.execute("""\
CREATE TABLE %(table)s (
  id bigserial PRIMARY KEY,
  q_name varchar(255),
  locked_at timestamptz,
  %(columns)s
);

CREATE INDEX idx_qc_on_name_only_unlocked ON %(table)s (q_name, id) WHERE locked_at IS NULL;

-- We are declaring the return type to be queue_classic_jobs.
-- This is ok since I am assuming that all of the users added queues will
-- have identical columns to queue_classic_jobs.
-- When QC supports queues with columns other than the default, we will have to change this.

CREATE OR REPLACE FUNCTION lock_head_%(table)s(q_name varchar, top_boundary integer)
RETURNS SETOF %(table)s AS $$
DECLARE
  unlocked bigint;
  relative_top integer;
  job_count integer;
BEGIN
  -- The purpose is to release contention for the first spot in the table.
  -- The select count(*) is going to slow down dequeue performance but allow
  -- for more workers. Would love to see some optimization here...

  EXECUTE 'SELECT count(*) FROM '
    || '(SELECT * FROM %(table)s WHERE q_name = '
    || quote_literal(q_name)
    || ' LIMIT '
    || quote_literal(top_boundary)
    || ') limited'
  INTO job_count;

  SELECT TRUNC(random() * (top_boundary - 1))
  INTO relative_top;

  IF job_count < top_boundary THEN
    relative_top = 0;
  END IF;

  LOOP
    BEGIN
      EXECUTE 'SELECT id FROM %(table)s '
        || ' WHERE locked_at IS NULL'
        || ' AND q_name = '
        || quote_literal(q_name)
        || ' ORDER BY id ASC'
        || ' LIMIT 1'
        || ' OFFSET ' || quote_literal(relative_top)
        || ' FOR UPDATE NOWAIT'
      INTO unlocked;
      EXIT;
    EXCEPTION
      WHEN lock_not_available THEN
        -- do nothing. loop again and hope we get a lock
    END;
  END LOOP;

  RETURN QUERY EXECUTE 'UPDATE %(table)s '
    || ' SET locked_at = (CURRENT_TIMESTAMP)'
    || ' WHERE id = $1'
    || ' AND locked_at is NULL'
    || ' RETURNING *'
  USING unlocked;

  RETURN;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION lock_head_%(table)s(tname varchar)
RETURNS SETOF %(table)s AS $$
BEGIN
  RETURN QUERY EXECUTE 'SELECT * FROM lock_head_%(table)s($1,10)' USING tname;
END;
$$ LANGUAGE plpgsql;""" % kwargs)
    return conn

def drop_queue(conn, **kwargs):
    conn.execute("""\
DROP FUNCTION IF EXISTS lock_head_%(table)s(tname varchar);
DROP FUNCTION IF EXISTS lock_head_%(table)s(q_name varchar, top_boundary integer);
DROP TABLE IF EXISTS %(table)s;""" % kwargs)
    return conn
