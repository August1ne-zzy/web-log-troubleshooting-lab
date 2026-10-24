-- Scope: every accepted, unique request in this database; all paths and statuses.
SELECT
    COUNT(*) AS request_count,
    MIN(timestamp) AS first_request_utc,
    MAX(timestamp) AS last_request_utc,
    COALESCE(SUM(status BETWEEN 400 AND 499), 0) AS client_error_count,
    COALESCE(SUM(status BETWEEN 500 AND 599), 0) AS server_error_count,
    COALESCE(SUM(status BETWEEN 400 AND 599), 0) AS error_count,
    ROUND(100.0 * SUM(status BETWEEN 400 AND 499) / NULLIF(COUNT(*), 0), 3) AS client_error_pct,
    ROUND(100.0 * SUM(status BETWEEN 500 AND 599) / NULLIF(COUNT(*), 0), 3) AS server_error_pct,
    ROUND(100.0 * SUM(status BETWEEN 400 AND 599) / NULLIF(COUNT(*), 0), 3) AS error_pct,
    ROUND(AVG(duration_ms), 3) AS avg_duration_ms,
    ROUND(MAX(duration_ms), 3) AS max_duration_ms,
    COALESCE(SUM(duration_ms >= :slow_ms), 0) AS slow_count,
    ROUND(100.0 * SUM(duration_ms >= :slow_ms) / NULLIF(COUNT(*), 0), 3) AS slow_pct
FROM requests;
