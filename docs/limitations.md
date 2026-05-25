# Limitations And Reporting Boundaries

FinSight is designed for reproducible report-generation evaluation, with clear boundaries on what its current artifacts demonstrate.

## What The Formal Result Shows

- On the frozen `formal18_fy2024_v1` protocol, Multi-Agent RAG achieves higher delivery, quality and traceability scores than the two one-shot baselines.
- All variants receive the same frozen case evidence; benchmark runtime fetching is prohibited.
- The manifest and summary artifacts preserve the input hash and result tables needed to audit that claim.

## What It Does Not Show

- It does not prove production stability on live, changing data sources.
- It does not establish investment return, investment recommendation accuracy or regulatory suitability.
- It does not guarantee equal coverage across markets: Formal-18 shows weak HK traceability and remaining CN-A delivery failures.
- It does not make optional model, network or vector-search dependencies universally available.

## Public Demonstration Policy

Published claims should remain tied to a dataset version, a named metric and the linked artifacts. Generated reports are research-system outputs and should not be represented as investment advice.
