"""Shared wire-contract identity, importable without the CAD runtime."""

CONTRACT_VERSION = 3
CONTRACT_REVISION = 2
# Largest request body (bytes) the bridge accepts, published by capabilities and
# the session file; batch.validate and the client read the same value.
REQUEST_SIZE_LIMIT = 65536
