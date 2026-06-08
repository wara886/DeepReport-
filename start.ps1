if (-not (Test-Path -LiteralPath ".env")) {
    Copy-Item -LiteralPath ".env.example" -Destination ".env"
    Write-Host "Created .env from .env.example; add credentials for remote report generation."
}

$env:HF_HOME = if ($env:HF_HOME) { $env:HF_HOME } else { Join-Path (Get-Location) "models\huggingface" }
$env:SENTENCE_TRANSFORMERS_HOME = if ($env:SENTENCE_TRANSFORMERS_HOME) { $env:SENTENCE_TRANSFORMERS_HOME } else { Join-Path (Get-Location) "models\sentence_transformers" }
$env:TRANSFORMERS_CACHE = if ($env:TRANSFORMERS_CACHE) { $env:TRANSFORMERS_CACHE } else { Join-Path (Get-Location) "models\huggingface\transformers" }
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = if ($env:HF_HUB_DISABLE_SYMLINKS_WARNING) { $env:HF_HUB_DISABLE_SYMLINKS_WARNING } else { "1" }

docker compose up --build -d
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host "FinSight is starting at http://localhost:7860"
