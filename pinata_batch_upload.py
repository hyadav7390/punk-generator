import argparse
import json
import mimetypes
import os
import sys
import time
from contextlib import ExitStack
from pathlib import Path
from typing import Iterable, List, Sequence

import requests

from x402_ipfs_service import (  # type: ignore
    BASE_BACKOFF,
    BATCH_PAUSE,
    DEFAULT_BATCH_SIZE,
    MAX_RETRIES,
    PINATA_API_BASE,
    PinataUploader,
    load_env_file,
)


def _iter_directory_files(directory: Path, include_metadata: bool) -> List[Path]:
    if not directory.exists():
        raise FileNotFoundError(f"Directory {directory} does not exist")

    files = sorted(path for path in directory.rglob("*.png") if path.is_file())

    metadata_path = directory / "metadata.json"
    if include_metadata and metadata_path.exists():
        files.append(metadata_path)

    if not files:
        raise RuntimeError(f"Directory {directory} does not contain any PNG files")
    return files


def _chunked(items: Sequence[Path], size: int) -> Iterable[List[Path]]:
    if size <= 0:
        yield list(items)
        return

    for index in range(0, len(items), size):
        yield list(items[index : index + size])


def _media_type(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"


def _upload_batch(
    uploader: PinataUploader,
    batch: List[Path],
    *,
    base_directory: Path,
    directory_name: str,
    batch_index: int,
    total_batches: int,
    max_retries: int,
    backoff: float,
    timeout: int,
) -> dict:
    endpoint = f"{uploader.base_url}/pinning/pinFileToIPFS"
    metadata_payload = {
        "name": f"{directory_name}-batch-{batch_index:03d}",
        "keyvalues": {"batch": str(batch_index), "total_batches": str(total_batches), "source_directory": directory_name},
    }
    options_payload = {"wrapWithDirectory": True}
    rate_limit_hits = 0

    for attempt in range(max_retries):
        try:
            with ExitStack() as stack:
                files_payload = []
                for item in batch:
                    handle = stack.enter_context(item.open("rb"))
                    relative_path = item.relative_to(base_directory)
                    rel_path = Path(directory_name) / relative_path
                    files_payload.append(("file", (rel_path.as_posix(), handle, _media_type(item))))

                response = requests.post(
                    endpoint,
                    headers=uploader._headers(),
                    files=files_payload,
                    data={
                        "pinataMetadata": json.dumps(metadata_payload),
                        "pinataOptions": json.dumps(options_payload),
                    },
                    timeout=timeout,
                )

            if response.status_code == 429:
                rate_limit_hits += 1
                sleep_for = backoff * (2 ** attempt)
                time.sleep(sleep_for)
                continue

            if response.status_code >= 500:
                sleep_for = backoff * (attempt + 1)
                time.sleep(sleep_for)
                continue

            response.raise_for_status()
            payload = response.json()
            return {
                "batch_index": batch_index,
                "cid": payload.get("IpfsHash"),
                "pin_size": payload.get("PinSize"),
                "timestamp": payload.get("Timestamp"),
                "files": [item.name for item in batch],
                "rate_limit_hits": rate_limit_hits,
            }
        except (requests.RequestException, OSError) as exc:
            if attempt == max_retries - 1:
                raise
            sleep_for = backoff * (2 ** attempt)
            time.sleep(sleep_for)

    raise RuntimeError(f"Failed to upload batch {batch_index}")


def _print_result(results: List[dict]) -> None:
    summary = {
        "batches": len(results),
        "total_files": sum(len(item["files"]) for item in results),
        "rate_limit_hits": sum(item["rate_limit_hits"] for item in results),
        "pinata_items": [{"batch": item["batch_index"], "cid": item["cid"], "pin_size": item["pin_size"]} for item in results],
    }
    print(json.dumps({"results": results, "summary": summary}, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upload generated assets to Pinata in batches")
    parser.add_argument("--env-file", type=Path, help="Optional .env file containing PINATA credentials")
    parser.add_argument("--directory", type=Path, default=Path(os.getenv("X402_OUTPUT_DIR", "generated")), help="Directory containing generated assets")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="Number of files per batch")
    parser.add_argument("--timeout", type=int, default=300, help="Request timeout in seconds")
    parser.add_argument("--max-retries", type=int, default=MAX_RETRIES, help="Maximum retries per batch")
    parser.add_argument("--backoff", type=float, default=BASE_BACKOFF, help="Base backoff (seconds) for retries")
    parser.add_argument("--pause", type=float, default=BATCH_PAUSE, help="Pause between batches in seconds")
    parser.add_argument("--directory-name", help="Folder name to use inside Pinata (defaults to directory name)")
    parser.add_argument("--include-metadata", action="store_true", dest="include_metadata", help="Include metadata.json if present")
    parser.add_argument("--exclude-metadata", action="store_false", dest="include_metadata", help="Skip metadata.json")
    parser.set_defaults(include_metadata=True)
    parser.add_argument("--dry-run", action="store_true", help="Show batches without uploading")
    parser.add_argument("--jwt", help="Pinata JWT (overrides PINATA_JWT)")
    parser.add_argument("--api-key", dest="api_key", help="Pinata API key (overrides PINATA_API_KEY)")
    parser.add_argument("--api-secret", dest="api_secret", help="Pinata API secret (overrides PINATA_API_SECRET)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.env_file:
        load_env_file(args.env_file)

    directory = args.directory
    files = _iter_directory_files(directory, args.include_metadata)

    if args.dry_run:
        batches = list(_chunked(files, args.batch_size))
        print(
            json.dumps(
                {
                    "directory": str(directory),
                    "total_files": len(files),
                    "batch_size": args.batch_size,
                    "batches": [{"index": index + 1, "count": len(batch), "files": [item.name for item in batch]} for index, batch in enumerate(batches)],
                },
                indent=2,
            )
        )
        return

    jwt = args.jwt or os.getenv("PINATA_JWT")
    api_key = args.api_key or os.getenv("PINATA_API_KEY")
    api_secret = args.api_secret or os.getenv("PINATA_API_SECRET")

    try:
        uploader = PinataUploader(PINATA_API_BASE, jwt, api_key, api_secret)
    except ValueError as exc:
        raise SystemExit(str(exc))

    directory_name = args.directory_name or directory.name or "generated"

    batches = list(_chunked(files, args.batch_size))
    total_batches = len(batches)

    results: List[dict] = []

    for index, batch in enumerate(batches, start=1):
        try:
            batch_result = _upload_batch(
                uploader,
                batch,
                base_directory=directory,
                directory_name=directory_name,
                batch_index=index,
                total_batches=total_batches,
                max_retries=args.max_retries,
                backoff=args.backoff,
                timeout=args.timeout,
            )
            results.append(batch_result)
        except (requests.RequestException, OSError, RuntimeError) as exc:
            print(f"Batch {index} failed: {exc}", file=sys.stderr)
            break

        if args.pause > 0 and index < total_batches:
            time.sleep(args.pause)

    if results:
        _print_result(results)
    else:
        raise SystemExit("No batches uploaded successfully")


if __name__ == "__main__":
    main()
