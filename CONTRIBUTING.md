# Contributing

Contributions are welcome when they preserve the fail-closed protocol and its evidence chain.

1. Fork the repository and create a focused branch.
2. Keep Worker output non-authoritative; Git and deterministic validators remain the source of truth.
3. Add or update tests for every protocol, Runtime, gate, or accounting change.
4. Run `PYTHONPATH=scripts/token_firewall_runtime python3 -m unittest discover -s tests/token_firewall -v`.
5. Open a pull request that explains the behavior change, risk boundary, and verification evidence.

Do not include model transcripts, credentials, private hidden tests, or machine-specific absolute paths.
