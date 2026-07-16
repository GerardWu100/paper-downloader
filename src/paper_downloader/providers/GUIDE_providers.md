# GUIDE_providers

This folder contains provider-specific URL builders and request-boundary helpers
for scholarly metadata services.

- `crossref.py` owns Crossref URL construction, polite-pool headers, and the
  timed JSON helper used by metadata export.
- `openalex.py` owns OpenAlex source and work URL construction.

Keep response-field extraction outside this folder. Provider modules should know how to ask a service for payloads, while metadata extraction code should know how to interpret those payloads.
