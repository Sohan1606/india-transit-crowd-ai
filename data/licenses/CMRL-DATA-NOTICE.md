# Chennai Metro Rail Limited (CMRL) data notice

**What this project stores.** Committed for Chennai: `data/processed/chennai_metro_demand_timeseries.metadata.json`
(provenance, checksums, coverage counts — no observations) and the trained artifacts under
`backend/models/chennai-cmrl-metro/`. **Not committed:** the upstream CSVs and the normalized
observation table `data/processed/chennai_metro_demand_timeseries.csv`, both git-ignored, because
both are the operator's numbers. Regenerate them with the two commands below; the committed
sidecar's `normalized_sha256` then verifies that you rebuilt the same dataset the model was
trained on.

**Why the raw archive is not bundled.** The numbers originate from CMRL's own passenger-flow
portal (`commuters-dataapi.chennaimetrorail.org`), served through the community tracker
`PratyushBalaji/chennai-metro-ridership-tracker`. That repository publishes an MIT
licence covering **its code**; it carries no grant for the underlying operator data, and
CMRL's portal shows no posted open-data licence for bulk historical reuse. Redistributing
the CSVs inside this repository would therefore rest on an assumption rather than a
documented permission.

**How to obtain the data legitimately.**

```bash
python3 scripts/download_cmrl_data.py     # fetches the pinned revision, verifies SHA-256
python3 scripts/prepare_chennai_data.py   # normalizes into the canonical record contract
```

Both steps take a few seconds and need no credentials. Without them the API answers
`503` for `chennai-cmrl-metro` with the reason `Normalized observed-demand data not found`,
and every other system keeps working.

The downloader refuses an unreviewed upstream revision (`--no-verify` exists for auditing,
not for shipping). Pinned revision `72ee5eadb6ca890bfd9900d6464a1a371566c86b`; checksums are
recorded in `ml/data_pipeline/cmrl.py` (`CMRL_CHECKSUMS`):

| upstream file | sha256 |
| --- | --- |
| `Ridership/ChennaiMetro_Station_Ridership.csv` | `2630ea1b083e491c225ec49760156b01302e8bfbd4383784045576306a709190` |
| `Ridership/ChennaiMetro_Daily_Ridership.csv` | `6f16712ee90aebeefa52ca49e4dc3f3c6e076368b4ab60a1783260e6adba02bc` |
| `Ridership/ChennaiMetro_Hourly_Ridership.csv` | `4ae938c6c392a8bba8d1d412f30083e62e6031feb51e97774efe072c3323f19e` |

**Attribution to use when quoting figures.** "Chennai Metro Rail Limited, passenger-flow
data, commuters-data.chennaimetrorail.org." The tracker's daily collection schedule (GitHub
Actions) is the archive mechanism, not the publisher of the counts.

**Status of the derived table.** It is generated, never shipped, and it is not committed even
though it is a transformation: a derived copy of a count table is still that count table. The
model artifacts are this project's own output and are shipped so that a clone can inspect the
benchmark numbers without re-downloading anything.

## Mumbai suburban railway (for contrast)

The MRVC / Wilbur Smith Executive Summary (2013) prints no licence or reuse statement. Its
extracted values live in `data/research/` with per-row page and table citations, the source
PDF is **not** committed, and the dataset is refused by the validation gate in
`scripts/extract_mumbai_pdf_surveys.py`. Re-download the document from MRVC before publishing
any figure from it.
