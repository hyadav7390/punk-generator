import argparse
import json
import mimetypes
import os
import sys
from contextlib import ExitStack
from pathlib import Path
from typing import List

import requests

from x402_ipfs_service import (  # type: ignore
    PINATA_API_BASE,
    PinataUploader,
    load_env_file,
)


def _list_directory_files(directory: Path, include_metadata: bool) -> List[Path]:
    if not directory.exists():
        raise FileNotFoundError(f"Directory {directory} does not exist")

    files = sorted(path for path in directory.rglob("*") if path.is_file())

    if not files:
        raise RuntimeError(f"Directory {directory} does not contain any files")

    if not include_metadata:
        files = [path for path in files if path.name != "metadata.json"]

    return files


def _media_type(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"


def upload_directory(
    uploader: PinataUploader,
    files: List[Path],
    *,
    base_directory: Path,
    directory_name: str,
    timeout: int,
) -> dict:
    endpoint = f"{uploader.base_url}/pinning/pinFileToIPFS"

    metadata_payload = {"name": directory_name}
    options_payload = {"wrapWithDirectory": True}

    with ExitStack() as stack:
        payload_files = []
        for file_path in files:
            handle = stack.enter_context(file_path.open("rb"))
            relative_path = file_path.relative_to(base_directory)
            entry_path = Path(directory_name) / relative_path
            payload_files.append(("file", (entry_path.as_posix(), handle, _media_type(file_path))))

        response = requests.post(
            endpoint,
            headers=uploader._headers(),
            files=payload_files,
            data={
                "pinataMetadata": json.dumps(metadata_payload),
                "pinataOptions": json.dumps(options_payload),
            },
            timeout=timeout,
        )

    response.raise_for_status()
    payload = response.json()
    return {
        "directory_cid": payload.get("IpfsHash"),
        "pin_size": payload.get("PinSize"),
        "timestamp": payload.get("Timestamp"),
        "file_count": len(files),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upload an entire directory to Pinata with a single CID")
    parser.add_argument("--env-file", type=Path, help="Optional .env file with Pinata credentials")
    parser.add_argument("--directory", type=Path, default=Path(os.getenv("X402_OUTPUT_DIR", "generated")), help="Directory to upload")
    parser.add_argument("--directory-name", help="Custom folder name inside Pinata (defaults to directory name)")
    parser.add_argument("--include-metadata", action="store_true", dest="include_metadata", help="Include metadata.json files (default: true)")
    parser.add_argument("--exclude-metadata", action="store_false", dest="include_metadata", help="Exclude metadata.json files")
    parser.set_defaults(include_metadata=True)
    parser.add_argument("--timeout", type=int, default=600, help="Request timeout in seconds")
    parser.add_argument("--jwt", help="Pinata JWT token")
    parser.add_argument("--api-key", dest="api_key", help="Pinata API key")
    parser.add_argument("--api-secret", dest="api_secret", help="Pinata API secret")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.env_file:
        load_env_file(args.env_file)

    directory = args.directory
    try:
        files = _list_directory_files(directory, args.include_metadata)
    except (FileNotFoundError, RuntimeError) as exc:
        raise SystemExit(str(exc))

    jwt = args.jwt or os.getenv("PINATA_JWT")
    api_key = args.api_key or os.getenv("PINATA_API_KEY")
    api_secret = args.api_secret or os.getenv("PINATA_API_SECRET")

    try:
        uploader = PinataUploader(PINATA_API_BASE, jwt, api_key, api_secret)
    except ValueError as exc:
        raise SystemExit(str(exc))

    directory_name = args.directory_name or directory.name or "upload"

    try:
        result = upload_directory(
            uploader,
            files,
            base_directory=directory,
            directory_name=directory_name,
            timeout=args.timeout,
        )
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.text:
            print(exc.response.text, file=sys.stderr)
        raise SystemExit(f"Upload failed: {exc}")
    except requests.RequestException as exc:
        raise SystemExit(f"Upload failed: {exc}")

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
