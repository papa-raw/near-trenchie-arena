# NFT media v1

`v1/` contains the five approved starter portraits as PNG and their starter attributes as JSON. The contract returns these absolute URLs and pins the exact PNG/JSON bytes with padded Base64 SHA256 hashes. The real HTTP transport is `near/web/snapin/serve.py`; `/nft/<preset>-NN.png` aliases the preset portrait. Versioned URLs have an immutable cache policy.

Do not overwrite published v1 files. A changed portrait, kit or reference needs a new version and an explicit contract upgrade. To prepare an unpublished version, run `python3 -B near/tools/prepare_nft_metadata.py`, render with `NODE_PATH=$HOME/.nvm/versions/node/v24.22.1/lib/node_modules node near/tools/render_nft_media.cjs`, then run the prepare command again to pin the new hashes. The renderer uses the existing premint look JSON, approved 3D art and starter kits. It respects the lane's proxy when configured.

A custom token keeps its signed name and uses its preset's starter portrait. The reference describes starter gear; live inventory and records remain on testnet under the unchanged identity token id. It does not claim to reflect later gear changes or a custom appearance absent from onchain state.

`migrate` adds no fields and replaces no tokens. Legacy missing wallet metadata is computed by `nft_token` and enumeration. New tokens store their actual mint time; missing historical mint times remain null. Migration emits contract and token metadata update events, bounded to 12 KiB of token ids so an unusually large old deployment cannot make the upgrade fail its log limit. All metadata views are enriched regardless of that notification bound.

NEP-199 returns the full input balance to the seller with zero creator royalties. `nft_transfer_payout` uses the ordinary guarded transfer path and returns a settlement mapping; the calling marketplace distributes funds.
