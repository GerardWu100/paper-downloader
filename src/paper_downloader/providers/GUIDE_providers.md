# GUIDE_providers

This folder isolates everything that depends on the wire format of one
scholarly metadata service.

- `crossref.py` owns Crossref URL construction, polite-pool headers, the
  `message` envelope, and publication-date parsing.
- `openalex.py` owns OpenAlex source and work URL construction plus headers.

## What belongs here

Anything whose correctness depends on how a specific provider shapes its
response: URL formats, header requirements, envelope keys, and the field
priority rules for reading a value out of a payload.

Provider-shape parsing lives here, not in the calling modules. Both
`naming.py` and `metadata/export.py` need the Crossref publication date, and
when each kept its own copy the two encoded the same key-priority list
independently and had to be edited together. One extractor in `crossref.py`
now serves both: `naming` takes the leading four characters for the year, and
the exporter uses the full `YYYY-MM-DD` string.

## What does not belong here

- HTTP transport. Provider modules build URLs and headers; `_http.py` performs
  the request. A pass-through fetch wrapper in a provider module is a mistake,
  because the module name then implies a provider restriction the code does not
  have.
- Merging across providers. Deciding that Crossref wins over OpenAlex for a
  given column is the caller's policy, and it lives in `metadata/export.py`.
