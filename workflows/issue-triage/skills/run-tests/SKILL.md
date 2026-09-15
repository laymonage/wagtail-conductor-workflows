---
name: run-tests
description: |
  Run the Wagtail test suite in this repo with ./runtests.py (NOT pytest).
  Use when adding or running tests inside the Wagtail checkout — for example
  verifying a candidate unit test — not for bakerydemo or fresh-project
  reproduction.
---

# Running tests in this repo

**This project does NOT use pytest.** Do not run `pytest`, `python -m pytest`, or `manage.py test`. Use the `./runtests.py` wrapper, which sets `DJANGO_SETTINGS_MODULE=wagtail.test.settings` and forwards any unrecognized args (verbosity, parallel, keepdb, tags, and dotted test paths) straight to Django's test runner.

## Standard command

```bash
DATABASE_NAME=default.sqlite3 ./runtests.py --verbosity=1 --keepdb --exclude-tag=transaction <dotted.test.path>
```

- `DATABASE_NAME=default.sqlite3` — use the persistent SQLite DB so `--keepdb` can reuse it.
- `--keepdb` — reuse the test DB between runs (much faster; skips recreate/migrate).
- `--parallel` — run tests across multiple processes, useful when running multiple tests.
- `--exclude-tag=transaction` — skip transaction tests, which are incompatible with `--keepdb` / parallel SQLite runs as it would destroy the test data from migrations.
- `--verbosity=1` — default verbosity; bump to `2` for more detail when debugging.

## Targeting tests

Pass Django dotted paths (NOT file paths) as positional args. Examples:

```bash
# A single TestCase class
DATABASE_NAME=default.sqlite3 ./runtests.py --verbosity=1 --parallel --keepdb --exclude-tag=transaction wagtail.tests.test_sites.TestSiteOrdering

# A whole module
DATABASE_NAME=default.sqlite3 ./runtests.py --verbosity=1 --parallel --keepdb --exclude-tag=transaction wagtail.contrib.settings.tests.site_specific.test_forms

# Multiple targets at once
DATABASE_NAME=default.sqlite3 ./runtests.py --verbosity=1 --parallel --keepdb --exclude-tag=transaction wagtail.tests.test_sites wagtail.contrib.settings

# A single test method
DATABASE_NAME=default.sqlite3 ./runtests.py --verbosity=1 --parallel --keepdb --exclude-tag=transaction wagtail.tests.test_sites.TestSiteOrdering.test_site_order_by_site_name
```

Run the full suite by omitting the positional path (slow — prefer targeting the relevant module).

## JavaScript unit tests

Client-side logic / UI components use Jest:

```bash
npm run test:unit
# A single file:
npm run test:unit -- client/src/components/Foo/Foo.test.js
```

(Playwright integration tests exist via `npm run test:integration` but need a running dev server — not worth running for typical changes.)

## Notes

- `runtests.py`-specific flags (defined in the wrapper): `--deprecation`, `--postgres`, `--elasticsearch7/8/9`, `--opensearch2/3`, `--emailuser`, `--disabletimezone`, `--bench`. Everything else is forwarded to Django.
- The first run with a fresh DB will build/migrate it; subsequent `--keepdb` runs are fast.
- **Stale DB after a migration:** if a new migration has landed since the last run, `--keepdb` with `--parallel` can break with SQLite ([known Django issue](https://code.djangoproject.com/ticket/26822)). Delete the parallel cloned DB files (`default_N.sqlite3`) and run again without `--parallel`. Subsequent runs can then be parallel again.
- To create migrations for the test app models after changing them: `django-admin makemigrations --settings=wagtail.test.settings`.
