# Upstream Sources

## Calculation Engine

- Package: `taibu-core@3.4.0`
- npm integrity: `sha512-4gg1rlIGxaeLXKMIM9TD2vG/WP8gbJP6VR7l49a2NTQe7G7iTOlR6lM2jymtJRryynQ7DT971ZofjcsHbmztog==`
- npm `gitHead`: `1f7f8920ef2c2b032401427623ac0b9a7496c68d`
- License: MIT, preserved in `LICENSE-taibu-core`

## Calendar Engine

- Package: `lunar-javascript@1.7.7`
- npm integrity: `sha512-u/KYiwPIBo/0bT+WWfU7qO1d+aqeB90Tuy4ErXenr2Gam0QcWeezUvtiOIyXR7HbVnW2I1DKfU0NBvzMZhbVQw==`
- License: MIT, preserved in `LICENSE-lunar-javascript`

## Place Resolver Source

- Repository commit: `14860a26e3c428bb9c0a3eee3ba88e7cb57b1e6c`
- Source path: `packages/mcp-server/src/place-resolution.ts`
- License: package-scoped MIT, preserved in `LICENSE-taibu-mcp-server`
- Original source SHA-256: `db335b6c1f62d863581014d410e9fcb8403a5ce6bb18a9d5d99d505d7f882742`
- Local adaptation preserves the Amap endpoint/request/response boundary and replaces fallback/manual-coordinate behavior with Marten validation and stable errors.
