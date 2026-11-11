# Demo Showcase

`scripts/seed_demo.py` creates an isolated workspace for demonstrations and screenshots.

- The workspace is always named `Demo Showcase`.
- It contains only fictional people, `example.com` email addresses, and reserved telephone numbers.
- It creates four non-production scenarios: appointment scheduling, candidate screening, retail support, and restaurant bookings.
- Calls are marked as simulations and projects use the `demo` engine, so they cannot originate real phone traffic.
- The script is idempotent. `--reset` removes only the reserved demo workspace and its related data.

The script never enumerates, copies, modifies, or deletes data belonging to any other workspace.
