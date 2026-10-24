"""Send four predictable GET requests per round to the local lab."""

import argparse
import time
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, build_opener


def send_requests(port, repeat=1):
    if repeat < 1:
        raise ValueError("repeat must be at least 1")
    results = []
    # Do not send loopback experiment traffic through an environment proxy.
    opener = build_opener(ProxyHandler({}))
    for round_number in range(1, repeat + 1):
        for path in ("/", "/missing", "/error", "/slow"):
            started = time.perf_counter()
            try:
                with opener.open(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
                    response.read()
                    status = response.status
            except HTTPError as response:
                # urllib represents HTTP 404/500 as exceptions, but the service replied.
                with response:
                    response.read()
                    status = response.code
            except (URLError, TimeoutError, OSError) as error:
                raise RuntimeError(f"Request failed for {path}: {error}. Check server terminal.") from error
            elapsed = (time.perf_counter() - started) * 1000
            results.append({"round": round_number, "path": path, "status": status, "client_ms": elapsed})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat must be at least 1")
    try:
        results = send_requests(args.port, args.repeat)
    except RuntimeError as error:
        parser.exit(1, f"{error}\n")
    for row in results:
        print(f"round={row['round']} path={row['path']:8} status={row['status']} client_ms={row['client_ms']:.1f}")


if __name__ == "__main__":
    main()
