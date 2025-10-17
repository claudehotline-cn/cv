USE cv_cp;
SELECT COUNT(*) AS cnt, MIN(ts) AS min_ts, MAX(ts) AS max_ts FROM logs;
SELECT id, DATE_FORMAT(ts,'%Y-%m-%d %H:%i:%s') AS ts, level, pipeline, node, LEFT(message,120) AS msg
FROM logs ORDER BY ts DESC LIMIT 10;
