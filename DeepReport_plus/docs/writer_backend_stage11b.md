# Stage 11B Writer Backend

Stage 11B introduces one non-placeholder writer backend path: `remote`.

## Goals

- Keep existing `template_only` and `mock` behavior unchanged.
- Add one real backend path for writer generation.
- Preserve automatic fallback to template rendering.

## Config

Backend config: `configs/model_backends.yaml`

- `writer_backend.mode`: `template_only | mock | remote | local_small`
- `writer_backend.common`:
  - `timeout`
  - `retry`
  - `max_tokens`
  - `temperature`
- `writer_backend.backends.remote`:
  - `model_name`
  - `base_url`
  - optional env indirection:
    - `model_name_env`
    - `base_url_env`
    - `api_key_env`

Runtime config switch: `configs/local_real_smoke.yaml`

- `generation.writer_mode`
- `generation.backend`
- `generation.backend_config_path`

## Fallback Contract

When backend generation fails (timeout, non-200 response, parse failure, empty text), writer falls back to template rendering and still outputs a report.

Writer debug file (`writer_debug.json`) includes:

- `backend_mode`
- `generation_time`
- `fallback_triggered`
- `section_count`
- `error_message`
