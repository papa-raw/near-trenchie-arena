"""Chain settings from an env file outside the repo. The file names accounts and key-file paths, never a key.

    TRENCHIE_NETWORK=testnet
    TRENCHIE_ARENA_ID=arena.<root>.testnet
    TRENCHIE_MARKET_ID=market.<root>.testnet
    TRENCHIE_NFT_ID=nft.<root>.testnet                         # the testnet inventory (rows filed by token id)
    TRENCHIE_IDENTITY_NFT_ID=<the trenchie identity NFT>       # mainnet (.near), or its testnet stand-in; owners are read here
    TRENCHIE_OPERATOR_KEY_FILE=/abs/path/<operator>.json     # legacy keychain JSON: account_id, public_key, private_key
    TRENCHIE_RESOLVER_KEY_FILE=/abs/path/<resolver>.json
    TRENCHIE_RPC=https://rpc.testnet.near.org                  # optional; comma list
    TRENCHIE_ARCHIVAL=https://archival-rpc.testnet.near.org,https://archival-rpc.testnet.fastnear.com   # optional
    TRENCHIE_IDENTITY_RPC=https://rpc.mainnet.near.org         # optional; comma list; read-only, no key ever sent

Mainnet holds only the trenchie identity (Pat, 2026-11-11): a token's owner is read from the identity NFT's
NEP-171 `nft_token`, by the same token id the testnet inventory files rows under. Every write stays on testnet.

The env file and both key files must sit outside the repo and be readable by their owner only.
A value that looks like a private key is refused: keys go in key files.
"""

import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

from . import near_tx, rpc

REPO = Path(__file__).resolve().parents[2]
REQUIRED = ("TRENCHIE_NETWORK", "TRENCHIE_ARENA_ID", "TRENCHIE_MARKET_ID", "TRENCHIE_NFT_ID",
            "TRENCHIE_IDENTITY_NFT_ID", "TRENCHIE_OPERATOR_KEY_FILE", "TRENCHIE_RESOLVER_KEY_FILE")
MAINNET_RPC = ["https://rpc.mainnet.near.org"]


def identity_rpc_default(identity_nft: str) -> list:
    """The identity NFT's read list by its network: a .near id reads mainnet, a .testnet stand-in reads testnet."""
    return list(MAINNET_RPC if identity_nft.endswith(".near") else rpc.TESTNET_RPC)


class ConfigError(ValueError):
    pass


def _outside_repo(path: Path, what: str) -> Path:
    p = path.expanduser().resolve()
    if p == REPO or REPO in p.parents:
        raise ConfigError(f"{what} {p} is inside the repo; keep it outside (keys never enter the repo)")
    return p


def _owner_only(path: Path, what: str) -> None:
    mode = path.stat().st_mode
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise ConfigError(f"{what} {path} is readable by others (mode {stat.filemode(mode)}); run chmod 600 on it")


def read_env(path) -> dict:
    p = _outside_repo(Path(path), "env file")
    _owner_only(p, "env file")
    out = {}
    for n, line in enumerate(p.read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" not in line:
            raise ConfigError(f"{p}:{n}: not KEY=VALUE")
        k, v = line.split("=", 1)
        v = v.strip().strip('"').strip("'")
        if v.startswith(("ed25519:", "secp256k1:")) and len(v) > 60:
            raise ConfigError(f"{p}:{n}: {k.strip()} holds a key; put keys in a key file and name its path")
        out[k.strip()] = v
    return out


def load_key(path) -> near_tx.Key:
    p = _outside_repo(Path(path), "key file")
    _owner_only(p, "key file")
    data = json.loads(p.read_text())
    if "account_id" not in data:
        raise ConfigError(f"key file {p} has no account_id")
    return near_tx.Key(data["account_id"], data["public_key"], data.get("private_key") or data["secret_key"])


@dataclass
class ChainConfig:
    network: str
    arena: str
    market: str
    nft: str
    operator_key_file: str
    resolver_key_file: str
    rpc_urls: list = field(default_factory=lambda: list(rpc.TESTNET_RPC))
    archival_urls: list = field(default_factory=lambda: list(rpc.TESTNET_ARCHIVAL))
    identity_nft: str = ""
    identity_rpc_urls: list = field(default_factory=list)

    @classmethod
    def from_env_file(cls, path) -> "ChainConfig":
        env = read_env(path)
        missing = [k for k in REQUIRED if not env.get(k)]
        if missing:
            raise ConfigError(f"env file is missing {', '.join(missing)}")
        if env["TRENCHIE_NETWORK"] != "testnet":
            raise ConfigError("only testnet is wired: a mainnet write needs Pat's yes on a measured price")
        for k in ("TRENCHIE_ARENA_ID", "TRENCHIE_MARKET_ID", "TRENCHIE_NFT_ID"):
            if not env[k].endswith(".testnet") or "coharness" in env[k].lower():
                raise ConfigError(f"{k} must be a .testnet account with a game name")
        ident = env["TRENCHIE_IDENTITY_NFT_ID"]
        if not ident.endswith((".near", ".testnet")) or "coharness" in ident.lower():
            raise ConfigError("TRENCHIE_IDENTITY_NFT_ID must be a .near (or a .testnet stand-in) account with a game name")
        if ident == env["TRENCHIE_NFT_ID"]:
            raise ConfigError("TRENCHIE_IDENTITY_NFT_ID names the testnet inventory NFT; owners are read only from the "
                              "identity NFT, never from the inventory's shadow tokens")
        cfg = cls(env["TRENCHIE_NETWORK"], env["TRENCHIE_ARENA_ID"], env["TRENCHIE_MARKET_ID"], env["TRENCHIE_NFT_ID"],
                  env["TRENCHIE_OPERATOR_KEY_FILE"], env["TRENCHIE_RESOLVER_KEY_FILE"], identity_nft=ident,
                  identity_rpc_urls=identity_rpc_default(ident))
        if env.get("TRENCHIE_IDENTITY_RPC"):
            cfg.identity_rpc_urls = [u.strip() for u in env["TRENCHIE_IDENTITY_RPC"].split(",") if u.strip()]
        if env.get("TRENCHIE_RPC"):
            cfg.rpc_urls = [u.strip() for u in env["TRENCHIE_RPC"].split(",") if u.strip()]
        if env.get("TRENCHIE_ARCHIVAL"):
            cfg.archival_urls = [u.strip() for u in env["TRENCHIE_ARCHIVAL"].split(",") if u.strip()]
        return cfg

    def rpc(self, **kw) -> rpc.Rpc:
        """Sends go to the RPC list; reads may also fall back to the archival nodes."""
        return rpc.Rpc(self.rpc_urls, read_urls=self.rpc_urls + self.archival_urls, **kw)

    def identity_rpc(self, **kw) -> rpc.Rpc:
        """Owner reads only: the identity NFT's own list, no archival and no key. A failure here holds a life."""
        if not self.identity_nft or not self.identity_rpc_urls:
            raise ConfigError("no identity NFT configured: owners are never read from the testnet inventory")
        return rpc.Rpc(self.identity_rpc_urls, read_urls=self.identity_rpc_urls, **kw)

    def keys(self) -> dict:
        return {"operator": load_key(self.operator_key_file), "resolver": load_key(self.resolver_key_file)}

    def public(self) -> dict:
        """What may be printed: ids and endpoints, no paths to keys."""
        return {"network": self.network, "arena": self.arena, "market": self.market, "nft": self.nft,
                "rpc": self.rpc_urls, "archival": self.archival_urls, "identity_nft": self.identity_nft,
                "identity_rpc": self.identity_rpc_urls}


def dry_run_config() -> ChainConfig:
    """Placeholder ids for a dry-run with no env file; they name no real account and nothing is sent."""
    return ChainConfig("testnet", "arena.dry-run.testnet", "market.dry-run.testnet", "nft.dry-run.testnet", "", "",
                       identity_nft="identity.dry-run.testnet")


def env_file_default() -> str | None:
    return os.environ.get("TRENCHIE_CHAIN_ENV")
