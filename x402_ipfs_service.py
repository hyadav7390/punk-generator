import argparse
import json
import math
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

import requests
from flask import Flask, jsonify, request

PINATA_API_BASE = os.getenv("PINATA_API_BASE", "https://api.pinata.cloud")
OUTPUT_DIR = Path(os.getenv("X402_OUTPUT_DIR", "generated"))
FILE_PREFIX = os.getenv("PUNK_PREFIX", "x402Punk")
DEFAULT_BATCH_SIZE = int(os.getenv("X402_PINATA_BATCH", "25"))
MAX_RETRIES = int(os.getenv("X402_PINATA_RETRIES", "6"))
BASE_BACKOFF = float(os.getenv("X402_PINATA_BACKOFF", "3.0"))
BATCH_PAUSE = float(os.getenv("X402_PINATA_BATCH_PAUSE", "1.5"))


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


class PinataUploader:
    def __init__(self, base_url: str, jwt: Optional[str], api_key: Optional[str], api_secret: Optional[str]) -> None:
        if not jwt and not (api_key and api_secret):
            raise ValueError("Provide PINATA_JWT or both PINATA_API_KEY and PINATA_API_SECRET.")

        self.base_url = base_url.rstrip("/")
        self.jwt = jwt
        self.api_key = api_key
        self.api_secret = api_secret

    def _headers(self) -> Dict[str, str]:
        if self.jwt:
            return {"Authorization": f"Bearer {self.jwt}"}
        return {
            "pinata_api_key": self.api_key or "",
            "pinata_secret_api_key": self.api_secret or "",
        }

    def upload_file(
        self,
        file_path: Path,
        *,
        max_retries: int = MAX_RETRIES,
        base_backoff: float = BASE_BACKOFF,
        timeout: int = 120,
        on_rate_limit: Optional[Callable[[], None]] = None,
    ) -> Dict[str, str]:
        endpoint = f"{self.base_url}/pinning/pinFileToIPFS"

        for attempt in range(max_retries):
            try:
                with file_path.open("rb") as handle:
                    files = {"file": (file_path.name, handle, "application/octet-stream")}
                    metadata = json.dumps({"name": file_path.stem})
                    data = {"pinataMetadata": metadata}
                    response = requests.post(
                        endpoint,
                        headers=self._headers(),
                        files=files,
                        data=data,
                        timeout=timeout,
                    )

                if response.status_code == 429:
                    if on_rate_limit:
                        on_rate_limit()
                    sleep_for = base_backoff * (2 ** attempt)
                    time.sleep(sleep_for)
                    continue

                if response.status_code >= 500:
                    sleep_for = base_backoff * (attempt + 1)
                    time.sleep(sleep_for)
                    continue

                response.raise_for_status()
                payload = response.json()
                return {
                    "name": file_path.name,
                    "cid": payload.get("IpfsHash"),
                    "size": payload.get("PinSize"),
                    "timestamp": payload.get("Timestamp"),
                }
            except (requests.RequestException, OSError) as exc:
                if attempt == max_retries - 1:
                    raise exc
                sleep_for = base_backoff * (2 ** attempt)
                time.sleep(sleep_for)

        raise RuntimeError(f"Failed to upload {file_path.name} after {max_retries} attempts")


class UploadJob:
    def __init__(self, files: List[Path], uploader: PinataUploader, batch_size: int) -> None:
        self.id = str(uuid.uuid4())
        self.files = files
        self.uploader = uploader
        self.batch_size = batch_size
        self.status = "queued"
        self.uploaded = 0
        self.total = len(files)
        self.results: List[Dict[str, Optional[str]]] = []
        self.errors: List[Dict[str, str]] = []
        self.rate_limit_hits = 0
        self._lock = threading.Lock()

    def to_dict(self) -> Dict[str, object]:
        with self._lock:
            return {
                "id": self.id,
                "status": self.status,
                "uploaded": self.uploaded,
                "total": self.total,
                "rate_limit_hits": self.rate_limit_hits,
                "results": list(self.results),
                "errors": list(self.errors),
            }

    def _record_result(self, result: Dict[str, Optional[str]]) -> None:
        with self._lock:
            self.results.append(result)
            self.uploaded += 1

    def _record_error(self, file_name: str, message: str) -> None:
        with self._lock:
            self.errors.append({"name": file_name, "error": message})
            self.uploaded += 1

    def _increment_rate_limit(self) -> None:
        with self._lock:
            self.rate_limit_hits += 1

    def _batched(self, iterable: Iterable[Path]) -> Iterable[List[Path]]:
        batch: List[Path] = []
        for item in iterable:
            batch.append(item)
            if len(batch) == self.batch_size:
                yield batch
                batch = []
        if batch:
            yield batch

    def run(self) -> None:
        with self._lock:
            self.status = "running"

        total_batches = max(1, math.ceil(self.total / self.batch_size)) if self.batch_size else 1

        for batch_index, batch in enumerate(self._batched(self.files), start=1):
            for file_path in batch:
                try:
                    result = self.uploader.upload_file(file_path, on_rate_limit=self._increment_rate_limit)
                    self._record_result(result)
                except requests.HTTPError as http_error:
                    if http_error.response is not None and http_error.response.status_code == 429:
                        self._increment_rate_limit()
                    self._record_error(file_path.name, str(http_error))
                except Exception as exc:  # pylint: disable=broad-except
                    self._record_error(file_path.name, str(exc))

            if BATCH_PAUSE > 0 and batch_index < total_batches:
                time.sleep(BATCH_PAUSE)

        with self._lock:
            self.status = "completed_with_errors" if self.errors else "completed"


class JobManager:
    def __init__(self) -> None:
        self.jobs: Dict[str, UploadJob] = {}
        self._lock = threading.Lock()

    def add(self, job: UploadJob) -> UploadJob:
        with self._lock:
            self.jobs[job.id] = job
        thread = threading.Thread(target=job.run, daemon=True)
        thread.start()
        return job

    def get(self, job_id: str) -> Optional[UploadJob]:
        with self._lock:
            return self.jobs.get(job_id)

    def remove(self, job_id: str) -> bool:
        with self._lock:
            return self.jobs.pop(job_id, None) is not None


def collect_files(directory: Path, prefix: str, limit: Optional[int] = None, skip: int = 0) -> List[Path]:
    if not directory.exists():
        raise FileNotFoundError(f"Directory {directory} does not exist")

    files = sorted(directory.glob(f"{prefix}_*.png"))
    if limit is not None:
        files = files[skip : skip + limit]
    elif skip:
        files = files[skip:]
    return files


def create_app(uploader: PinataUploader) -> Flask:
    app = Flask(__name__)
    jobs = JobManager()

    @app.get("/health")
    def health() -> tuple:
        return jsonify({"status": "ok"})

    @app.post("/upload-x402")
    def upload_x402() -> tuple:
        payload = request.get_json(silent=True) or {}
        directory = Path(payload.get("directory", OUTPUT_DIR))
        limit = payload.get("limit")
        skip = int(payload.get("skip", 0))
        batch_size = int(payload.get("batch_size", DEFAULT_BATCH_SIZE))

        try:
            limit_int = int(limit) if limit is not None else None
        except (TypeError, ValueError):
            return jsonify({"error": "limit must be an integer"}), 400

        try:
            files = collect_files(directory, FILE_PREFIX, limit=limit_int, skip=skip)
        except FileNotFoundError as exc:
            return jsonify({"error": str(exc)}), 404

        if not files:
            return jsonify({"error": "No matching files found"}), 404

        job = UploadJob(files, uploader, batch_size)
        jobs.add(job)
        return jsonify({"job_id": job.id, "total": job.total})

    @app.get("/jobs/<job_id>")
    def job_status(job_id: str) -> tuple:
        job = jobs.get(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404
        return jsonify(job.to_dict())

    @app.delete("/jobs/<job_id>")
    def job_remove(job_id: str) -> tuple:
        removed = jobs.remove(job_id)
        if not removed:
            return jsonify({"error": "Job not found"}), 404
        return jsonify({"removed": job_id})

    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upload x402 punks to Pinata/IPFS")
    parser.add_argument("--env-file", help="Optional .env file with PINATA_* variables")
    parser.add_argument("--jwt", help="Pinata JWT token")
    parser.add_argument("--api-key", dest="api_key", help="Pinata API key")
    parser.add_argument("--api-secret", dest="api_secret", help="Pinata API secret")
    parser.add_argument("--host", help="Service host (overrides X402_SERVICE_HOST)")
    parser.add_argument("--port", type=int, help="Service port (overrides X402_SERVICE_PORT)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.env_file:
        load_env_file(Path(args.env_file))

    jwt = args.jwt or os.getenv("PINATA_JWT")
    api_key = args.api_key or os.getenv("PINATA_API_KEY")
    api_secret = args.api_secret or os.getenv("PINATA_API_SECRET")

    try:
        uploader = PinataUploader(PINATA_API_BASE, jwt, api_key, api_secret)
    except ValueError as exc:
        raise SystemExit(str(exc))

    app = create_app(uploader)
    host = args.host or os.getenv("X402_SERVICE_HOST", "0.0.0.0")
    port = args.port or int(os.getenv("X402_SERVICE_PORT", "5003"))
    app.run(host=host, port=port)


if __name__ == "__main__":
    main()
