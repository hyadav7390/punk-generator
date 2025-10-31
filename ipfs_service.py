import argparse
import json
import os
from pathlib import Path
from typing import Iterable, List

import requests
from flask import Flask, jsonify, request

DEFAULT_API_URL = os.getenv("IPFS_API_URL", "http://127.0.0.1:5001")
DEFAULT_OUTPUT_DIR = Path(os.getenv("PUNK_OUTPUT_DIR", "generated"))


class IPFSUploader:
    def __init__(self, api_url: str) -> None:
        self.api_url = api_url.rstrip("/")

    def add_files(self, files: Iterable[Path], *, wrap: bool = True, pin: bool = True, timeout: int = 60) -> List[dict]:
        file_list = list(files)
        if not file_list:
            return []

        endpoint = f"{self.api_url}/api/v0/add"
        payload = []
        for path in file_list:
            data = path.read_bytes()
            payload.append(("file", (path.name, data, "application/octet-stream")))

        params = {"pin": str(pin).lower()}
        if wrap:
            params["wrap-with-directory"] = "true"

        response = requests.post(endpoint, params=params, files=payload, timeout=timeout)
        response.raise_for_status()
        lines = [line for line in response.text.strip().splitlines() if line]
        return [json.loads(line) for line in lines]

    def add_directory(self, directory: Path, *, include_metadata: bool = True, pin: bool = True) -> List[dict]:
        if not directory.exists():
            raise FileNotFoundError(f"Directory {directory} does not exist")

        files = sorted(directory.glob("*.png"))
        if include_metadata:
            metadata_path = directory / "metadata.json"
            if metadata_path.exists():
                files.append(metadata_path)

        return self.add_files(files, pin=pin)


def create_app(uploader: IPFSUploader, output_dir: Path) -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index() -> tuple:
        return (
            jsonify(
                {
                    "message": "CryptoPunk generator upload service",
                    "endpoints": {
                        "health": "GET /health",
                        "upload": "POST /upload",
                    },
                    "instructions": "POST /upload with optional JSON body {directory, include_metadata, pin}.",
                }
            ),
            200,
        )

    @app.get("/health")
    def health() -> tuple:
        return jsonify({"status": "ok"})

    @app.post("/upload")
    def upload() -> tuple:
        payload = request.get_json(silent=True) or {}
        directory = Path(payload.get("directory", output_dir))
        include_metadata = bool(payload.get("include_metadata", True))
        pin = bool(payload.get("pin", True))

        try:
            results = uploader.add_directory(directory, include_metadata=include_metadata, pin=pin)
        except FileNotFoundError:
            return jsonify({"error": f"Directory {directory} not found"}), 404
        except requests.RequestException as exc:
            return jsonify({"error": "IPFS API request failed", "details": str(exc) or exc.__class__.__name__}), 502

        filtered = []
        for item in results:
            if not include_metadata and item.get("Name", "").endswith("metadata.json"):
                continue
            filtered.append({"name": item.get("Name"), "cid": item.get("Hash"), "size": item.get("Size")})

        if not filtered:
            return jsonify({"message": "No files uploaded"})

        summary = {"files": filtered, "directory_cid": results[-1].get("Hash") if results else None}
        return jsonify(summary)

    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upload generated punks to IPFS")
    parser.add_argument("mode", choices=["serve", "oneshot"], nargs="?", default="serve")
    parser.add_argument("--api", dest="api", default=DEFAULT_API_URL, help="Base URL for the IPFS API")
    parser.add_argument("--directory", dest="directory", default=str(DEFAULT_OUTPUT_DIR), help="Directory containing generated assets")
    parser.add_argument("--host", dest="host", default="0.0.0.0", help="Host to bind when running the service")
    parser.add_argument("--port", dest="port", type=int, default=5002, help="Port to bind when running the service")
    parser.add_argument("--include-metadata", dest="include_metadata", action="store_true", help="Include metadata.json when running in oneshot mode")
    parser.add_argument("--no-include-metadata", dest="include_metadata", action="store_false")
    parser.set_defaults(include_metadata=True)
    parser.add_argument("--pin", dest="pin", action="store_true", help="Pin uploaded content (oneshot mode)")
    parser.add_argument("--no-pin", dest="pin", action="store_false")
    parser.set_defaults(pin=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.directory)
    uploader = IPFSUploader(args.api)

    if args.mode == "oneshot":
        try:
            results = uploader.add_directory(output_dir, include_metadata=args.include_metadata, pin=args.pin)
        except FileNotFoundError as exc:
            raise SystemExit(str(exc))
        except requests.RequestException as exc:
            raise SystemExit(f"IPFS API request failed: {exc}")

        for item in results:
            print(json.dumps(item))
        return

    app = create_app(uploader, output_dir)
    app.run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
