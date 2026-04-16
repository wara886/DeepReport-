# Real Data Contract (Stage 11A)

## Purpose

This document defines the minimum local-file protocol for Stage 11A real data ingestion.
The scope is intentionally small:

- single `symbol`
- single `period`
- no online fetching
- only local files

## Directory Structure

```text
data/raw/real_data/<symbol>/<period>/
  company_profile.json
  financials.csv
  market.csv
  news.jsonl
  filings.jsonl
```

Example:

```text
data/raw/real_data/AAPL/2025Q4/
  company_profile.json
  financials.csv
  market.csv
  news.jsonl
  filings.jsonl
```

## Global Rules

- Encoding: UTF-8
- Date/time format: ISO 8601 string (`YYYY-MM-DD` or `YYYY-MM-DDTHH:MM:SSZ`)
- Missing value policy:
  - required field: must be present and non-empty
  - optional numeric field: allow empty string
  - optional text field: allow empty string
- Each record must map to manifest fields:
  - `sample_id` (generated if missing)
  - `source_type`
  - `symbol`
  - `period`
  - `title`
  - `publish_time`
  - `content`
  - `source_url`
  - `trust_level`

## File-Level Contract

### 1) `company_profile.json`

Type: single JSON object.

Required fields:

- `symbol`
- `period`
- `company_name`
- `industry`
- `sector`
- `description`
- `as_of_date`
- `source_url`
- `trust_level`

### 2) `financials.csv`

Type: CSV with header.

Required columns:

- `symbol`
- `period`
- `publish_time`
- `revenue_billion`
- `gross_margin_pct`
- `source_url`
- `trust_level`

Optional columns:

- `notes`

### 3) `market.csv`

Type: CSV with header.

Required columns:

- `symbol`
- `period`
- `publish_time`
- `close`
- `volume`
- `source_url`
- `trust_level`

### 4) `news.jsonl`

Type: JSON Lines (one JSON object per line).

Required fields per line:

- `symbol`
- `period`
- `title`
- `publish_time`
- `content`
- `source_url`
- `trust_level`

### 5) `filings.jsonl`

Type: JSON Lines.

Required fields per line:

- `symbol`
- `period`
- `title`
- `publish_time`
- `content`
- `source_url`
- `trust_level`

