"""Data layer exports for Stage 2."""

from src.data.fetch_base import BaseFetcher
from src.data.fetch_company_profile import CompanyProfileFetcher
from src.data.fetch_financials import FinancialsFetcher
from src.data.fetch_filings import FilingsFetcher
from src.data.fetch_market import MarketFetcher
from src.data.fetch_news import NewsFetcher
from src.data.manifest import build_manifest, write_manifest_json, write_manifest_parquet
from src.data.company_universe import load_company_universe, resolve_company_identifier, resolve_symbol
from src.data.independent_sources import fetch_independent_evidence_bundle, fetch_macro_evidence, fetch_sec_companyfacts_evidence
from src.data.sec_filing_resolver import resolve_sec_annual_filing

__all__ = [
    "BaseFetcher",
    "CompanyProfileFetcher",
    "MarketFetcher",
    "FinancialsFetcher",
    "NewsFetcher",
    "FilingsFetcher",
    "build_manifest",
    "write_manifest_parquet",
    "write_manifest_json",
    "load_company_universe",
    "resolve_company_identifier",
    "resolve_symbol",
    "fetch_independent_evidence_bundle",
    "fetch_macro_evidence",
    "fetch_sec_companyfacts_evidence",
    "resolve_sec_annual_filing",
]
