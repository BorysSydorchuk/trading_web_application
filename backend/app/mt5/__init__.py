"""Read-only MT5 access (PRD 6.2): source interface, real terminal, fixtures, conversion.

- `source.Mt5Source`: the protocol (raw records, server-time epochs).
- `real.RealMt5Source`: MetaTrader5 package (Windows).
- `fixture.FixtureMt5Source`: JSON fixtures for tests.
- `convert`: raw records -> domain `Deal`/`OrderStops`/`PositionSnapshot` with UTC times.
"""
