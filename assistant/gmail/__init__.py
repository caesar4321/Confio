"""Gmail pilot for Confío IA (approved 2026-11-22): read, and send only what the owner confirms.

Off unless configured and the user is on the tester list. Mail is never stored:
it is read from Gmail when needed and dropped. Mail is hostile input, so the
code that shows it to a model gives that model no tools, no history and no
account data. See docs/designs/assistant-mail-calendar.md.
"""
