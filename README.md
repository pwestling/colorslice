# Colorslice

Colorslice finds human-made reference art whose chromatic content fits inside a
selected slice of a perceptual color wheel. The initial sources are official
Magic: The Gathering printings from Scryfall and public-domain museum works.

## Develop locally

```bash
uv sync
uv run python -m scripts.ingest --source all --limit 80
uv run python main.py
```

The app runs at <http://127.0.0.1:5001>. Without `DATABASE_URL`, Colorslice uses
`data/colorslice.db`. When `DATABASE_URL` is present it uses Postgres.

## Ingest artwork

```bash
uv run python -m scripts.ingest --source magic --limit 200
uv run python -m scripts.ingest --source met --limit 200
uv run python -m scripts.ingest_balanced_magic --add 2000
```

Ingestion downloads small analysis images, converts meaningful chromatic pixels
to OKLCH, stores 72-bin area- and chroma-weighted hue histograms, and keeps only source image URLs and
provenance metadata. It does not generate, recolor, or permanently download the
display artwork.

The balanced Magic importer allocates additions to the least-represented
five-year release eras, then balances within each era by year. It excludes card
titles already in the catalog so repeated staples do not crowd out broader art.

## Deploy

The root `main.py` exposes the ASGI app expected by Vercel. With `DATABASE_URL`,
the app creates its Postgres schema and copies the bundled starter catalog into
an empty database on first boot. Without Postgres, Vercel copies `data/seed.db`
to its writable temporary filesystem so the starter gallery still works.
