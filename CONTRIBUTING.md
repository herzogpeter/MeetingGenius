# Contributing

Thanks for helping improve MeetingGenius.

## Local setup

### Prerequisites

- Python 3.10+
- (Optional) Node.js + npm (for `apps/web`)

### Python

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e .
python -m compileall -q src
```

### Web app (optional)

```bash
cd apps/web
npm ci
npm run build
```

## Branch naming

- `feat/<short-description>` for new features
- `fix/<short-description>` for bug fixes
- `chore/<short-description>` for maintenance/refactors

## Pull request checklist

- [ ] Scope is small and focused
- [ ] Docs updated (README and/or `docs/` as needed)
- [ ] Smoke test run (`python -m compileall -q src` and any relevant manual checks)
- [ ] No secrets committed (use `.env.example`)
