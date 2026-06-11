"""Claude Code hook entrypoints — the thin signal layer of persistent-memory.

Each module is a standalone `python -m` entrypoint wired into Claude Code's
hook events. Hooks only read the event payload, track a small message counter,
and send short-timeout signals to the local daemon; they never do heavy work
and never fail the host session.
"""
