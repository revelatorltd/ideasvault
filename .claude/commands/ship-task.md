Close out the task we just finished: $ARGUMENTS

1. Run `pytest -q`. If anything fails, stop and report — do not proceed.
2. Run the task's acceptance command from docs/PLAN.md and paste the real output.
3. Only if both pass, check the task's box in docs/PLAN.md.
4. Commit with the message `$ARGUMENTS` prefixed by the task ID.

If the acceptance command cannot be run in this environment (it needs a deployed
host, a phone, or a Cloudflare console), say so plainly and leave the box unchecked.
