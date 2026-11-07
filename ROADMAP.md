# Roadmap

The following work is planned independently of the current implementation.

## Reliability and Provider Support

- Add contract tests for every voice and telephony provider adapter.
- Complete direct inbound routing for supported SIP providers.
- Add durable job handling for post-call processing and provider retries.
- Add tenant-scoped diagnostics and provider health checks.

## Agent Quality

- Build repeatable prompt and retrieval evaluation suites.
- Add retrieval-quality metrics and source-citation inspection.
- Improve interruption, turn-taking, and transcript consolidation tests.
- Add safe fixtures for multilingual voice simulations.

## Product and Accessibility

- Complete English and Italian interface coverage and automated localization checks.
- Audit keyboard navigation, focus behavior, contrast, and screen-reader labels.
- Improve mobile layouts for project configuration and call analysis.
- Add exportable synthetic reports for demonstrations.

## Operations

- Document reproducible local and production deployment paths.
- Add backup, restore, retention, and tenant-deletion runbooks.
- Add structured audit events for privileged administration actions.
- Add monitoring dashboards and alert thresholds for failed call processing.
