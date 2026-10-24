SELECT
    path,
    COUNT(*) AS request_count,
    SUM(status BETWEEN 400 AND 499) AS client_error_count,
    SUM(status BETWEEN 500 AND 599) AS server_error_count,
    ROUND(100.0 * SUM(status BETWEEN 400 AND 599) / COUNT(*), 3) AS error_pct,
    ROUND(AVG(duration_ms), 3) AS avg_duration_ms,
    ROUND(MAX(duration_ms), 3) AS max_duration_ms,
    SUM(duration_ms >= :slow_ms) AS slow_count
FROM requests
GROUP BY path
ORDER BY path;
