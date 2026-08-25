Verify the vault against its own spec. Do not fix anything; report only.

1. Run `pytest -q` and show the output.
2. Check each architecture invariant in CLAUDE.md against the current code, and state
   for each whether it holds, with the file and line that proves it.
3. Check each of the 14 test requirements in docs/SPEC.md §7 and say which are
   covered by an actual test and which are not.
4. List anything in `git diff` since the last commit that touches db.py, ingest.py, or
   the templates, and flag any change that weakens invariant 1 or invariant 5.

Finish with a single line: PASS or FAIL, plus the count of unmet items.
