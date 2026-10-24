CREATE TABLE IF NOT EXISTS requests (
    request_id TEXT PRIMARY KEY NOT NULL,
    timestamp TEXT NOT NULL,
    environment TEXT NOT NULL CHECK (environment = 'local-lab'),
    traffic_type TEXT NOT NULL CHECK (traffic_type = 'synthetic'),
    method TEXT NOT NULL CHECK (method = 'GET'),
    path TEXT NOT NULL,
    status INTEGER NOT NULL CHECK (status BETWEEN 100 AND 599),
    duration_ms REAL NOT NULL CHECK (duration_ms >= 0)
);
