# cryptopunkgenerator
### Generate CryptoPunk-style avatars

![Sample!](images/sample.jpg?raw=true "Sample!")

#### Usage 

```bash
pip3 install -r requirements.txt
```

Generate punks (defaults: 100 images, filenames `x402Punk_<n>.png` in `generated/`):

```bash
source .venv/bin/activate
python generatePunks.py
```

Environment knobs:

- `PUNK_COUNT` &mdash; total punks to generate (set to `10000` before running to prepare the full x402 drop).
- `PUNK_PREFIX` &mdash; filename prefix (defaults to `x402Punk`).

### Uploading generated punks to a local IPFS node

1. Install the dependencies:

   ```bash
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Start a local or remote IPFS node and expose its HTTP API (default `http://127.0.0.1:5001`).

3. Run the upload service:

   ```bash
   python ipfs_service.py serve --api http://127.0.0.1:5001 --port 5002
   ```

   Use `POST /upload` to push the contents of the `generated/` directory to IPFS. Optional JSON body:

   ```json
   {
     "directory": "generated",
     "include_metadata": true,
     "pin": true
   }
   ```

4. To perform a one-off upload without running the server:

   ```bash
   python ipfs_service.py oneshot --api http://127.0.0.1:5001 --directory generated
   ```

### Uploading 10,000 x402 punks to Pinata/IPFS

1. Provide your Pinata credentials (never commit them):

   ```bash
   export PINATA_JWT="<your_jwt_token>"
   # or alternatively
   export PINATA_API_KEY="<your_api_key>"
   export PINATA_API_SECRET="<your_api_secret>"
   ```

   You can also place the values in a local `.env` file (key=value per line) and start the service with `python x402_ipfs_service.py --env-file .env`, or pass them directly on the command line using `--jwt`, `--api-key`, and `--api-secret`.

2. Generate the full collection if you have not already:

   ```bash
   export PUNK_COUNT=10000
   python generatePunks.py
   ```

3. Start the dedicated uploader service (defaults: port `5003`, batch size `25` files, 1.5s pause between batches):

   ```bash
   python x402_ipfs_service.py
   ```

4. Kick off an upload job:

   ```bash
   curl -X POST http://localhost:5003/upload-x402 -H 'Content-Type: application/json' \
     -d '{"directory": "generated", "limit": 10000, "batch_size": 25}'
   ```

   The response includes a `job_id`. Poll progress and review rate-limit hits:

   ```bash
   curl http://localhost:5003/jobs/<job_id>
   ```

   Tweak pacing via environment variables:

   - `X402_PINATA_BATCH` &mdash; files per batch (default `25`).
   - `X402_PINATA_BATCH_PAUSE` &mdash; seconds to wait between batches (default `1.5`).
   - `X402_PINATA_RETRIES` / `X402_PINATA_BACKOFF` &mdash; retry behaviour when rate-limited.

---------------------------------------------

#### To do eventually, probably
+ Add more attributes
+ Capture generated punk metadata
+ More closely align probability to the original punks
+ Post another blog on the above

---------------------------------------------

#### Links

[CryptoPunks](https://larvalabs.com/cryptopunks)

[Original blog post](https://snoozesecurity.blogspot.com/)
