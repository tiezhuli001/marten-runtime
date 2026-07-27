# Marten Patches

## `sect1-v1`

The patch calls `setSect(1)` at three behavior-bearing EightChar sites:

1. Bazi chart calculation.
2. Dayun natal chart calculation.
3. Reverse-pillar final candidate validation, with the sect 1 Zi-hour civil-date offset required to enumerate both 23:00 and 00:00 candidates.

Reverse-pillar year, month, and day prefilters retain their upstream behavior. The final candidate loop maps Zi-hour 23:00 to the preceding civil date before applying sect 1 validation. `upstream-lock.json` records the exact original and patched SHA-256 digest for each changed file. Run `npm run verify:upstream` before and after `npm run prepare:engine`.
