"""The arena server's link to NEAR testnet: seed commits, the hourly batch, the stake resolver, archival reads.

Dry-run is the default everywhere: nothing is sent unless `--chain testnet` is given with an env file
outside the repo. `writer.py` states the rules each write keeps; `archival.py` reads a settled batch back.
"""
