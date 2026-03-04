## Description
## Change Impact Checklist Validation
- [ ] I have reviewed `docs/CHANGE_IMPACT_CHECKLIST.md`.
- [ ] I have updated all required derived files (e.g., lockfiles, VS Code extension paths).
- [ ] Pre-commit hooks (`Bandit`, `detect-secrets`, `Black`) pass locally without `--no-verify`.
- [ ] Any test secrets added are explicitly marked with `# nosec B105  # pragma: allowlist secret` on a single line.

## Related Issues
