import argparse
import json
import mimetypes
import os
import sys
from contextlib import ExitStack
from pathlib import Path
from typing import Dict, List, Optional

import requests

from x402_ipfs_service import load_env_file  # type: ignore

FILEBASE_API_BASE = os.getenv("FILEBASE_API_BASE", "https://api.filebase.io/v1")


def _ensure_token(explicit: Optional[str] = None) -> str:
    token = explicit or os.getenv("FILEBASE_TOKEN") or os.getenv("FILEBASE_API_TOKEN")
    if not token:
        raise ValueError(
            "Provide a Filebase API token via --token or FILEBASE_TOKEN/FILEBASE_API_TOKEN environment variable."
        )
    return token


def _list_directory_contents(directory: Path, include_metadata: bool) -> List[Path]:
    if not directory.exists():
        raise FileNotFoundError(f"Directory {directory} does not exist")

    files = sorted(path for path in directory.rglob("*") if path.is_file())
    if not files:
        raise RuntimeError(f"Directory {directory} does not contain any files")

    if not include_metadata:
        files = [path for path in files if path.name != "metadata.json"]

    if not files:
        raise RuntimeError(f"No files left to upload from {directory} after applying filters")

    return files


def _detect_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"


def _upload_to_filebase(
    token: str,
    files: List[Path],
    *,
    base_directory: Path,
    folder_name: str,
    timeout: int,
) -> Dict[str, object]:
    endpoint = f"{FILEBASE_API_BASE.rstrip('/')}/ipfs/add"
    params = {"wrap-with-directory": "true", "pin": "true"}

    with ExitStack() as stack:
        payload = []
        for path in files:
            handle = stack.enter_context(path.open("rb"))
            relative = path.relative_to(base_directory)
            remote_path = Path(folder_name) / relative
            payload.append(("path", (remote_path.as_posix(), handle, _detect_mime(path))))

        response = requests.post(
            endpoint,
            params=params,
            headers={"Authorization": f"Bearer {token}"},
            files=payload,
            timeout=timeout,
        )

    response.raise_for_status()
    lines = [json.loads(line) for line in response.text.strip().splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("Unexpected Filebase response: empty body")

    directory_info = lines[-1]
    file_entries = [
        {"name": item.get("Name"), "cid": item.get("Hash"), "size": item.get("Size")}
        for item in lines[:-1]
    ]
    return {
        "directory_name": directory_info.get("Name"),
        "directory_cid": directory_info.get("Hash"),
        "directory_size": directory_info.get("Size"),
        "file_count": len(files),
        "pinned_files": file_entries,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upload a directory to Filebase IPFS with a single folder CID")
    parser.add_argument("--env-file", type=Path, help="Optional .env file containing FILEBASE_TOKEN")
    parser.add_argument("--directory", type=Path, default=Path(os.getenv("X402_OUTPUT_DIR", "generated")), help="Directory to upload")
    parser.add_argument("--directory-name", help="Folder name to use within Filebase (defaults to directory name)")
    parser.add_argument("--include-metadata", action="store_true", dest="include_metadata", help="Include metadata.json files")
    parser.add_argument("--exclude-metadata", action="store_false", dest="include_metadata", help="Exclude metadata.json files")
    parser.set_defaults(include_metadata=True)
    parser.add_argument("--timeout", type=int, default=600, help="HTTP timeout (seconds)")
    parser.add_argument("--token", help="Filebase API token (overrides environment variable)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.env_file:
        load_env_file(args.env_file)

    directory = args.directory
    try:
        files = _list_directory_contents(directory, args.include_metadata)
    except (FileNotFoundError, RuntimeError) as exc:
        raise SystemExit(str(exc))

    try:
        token = _ensure_token(args.token)
    except ValueError as exc:
        raise SystemExit(str(exc))

    folder_name = args.directory_name or directory.name or "upload"

    try:
        result = _upload_to_filebase(
            token,
            files,
            base_directory=directory,
            folder_name=folder_name,
            timeout=args.timeout,
        )
    except requests.HTTPError as exc:
        details = exc.response.text if exc.response is not None else ""
        if details:
            print(details, file=sys.stderr)
        raise SystemExit(f"Upload failed: {exc}")
    except requests.RequestException as exc:
        raise SystemExit(f"Upload failed: {exc}")

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
