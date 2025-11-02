SELECT COUNT(*) AS cnt, MIN(ts) AS min_ts, MAX(ts) AS max_ts FROM cv_cp.logs;
SELECT id, DATE_FORMAT(ts,'%Y-%m-%d %H:%i:%s') AS ts, level, pipeline, node, LEFT(message,120) AS msg
FROM cv_cp.logs ORDER BY ts DESC LIMIT 10;
