# Contributing

## Default development workflow

Use the repository guidance in `AGENTS.md`, `CLAUDE.md`, and `docs/DEVELOPER.md`, then make and verify the smallest change that satisfies the request. Spec Kit is not the default workflow. Do not invoke Spec Kit commands or create `specs/` or `.specify/` artifacts unless the user explicitly asks for Spec Kit. A lightweight written plan is enough when the task benefits from one.

Keep changes focused, preserve existing user data, and do not claim tests or platform checks that were not run. For functional changes, run the relevant regression tests and the full suite when practical. For release work, follow the signed release steps in `docs/DEVELOPER.md`.

## Release checklist

1. Update `websync/__init__.py` and add `docs/releases/vX.Y.Z.md`.
2. Commit and push the release commit to `main`.
3. Wait for both required CI jobs to pass.
4. Create and push the matching `vX.Y.Z` tag.
5. Confirm the Release workflow built and smoke-checked the Windows executable, published the signed manifest, and updated `updates/latest.json`.
