# Contributing to StoryCraftr

Thank you for your interest in contributing to **StoryCraftr**! We welcome contributions from everyone and encourage collaboration to make this project better. Whether you’re a developer, a writer, or someone passionate about improving writing tools, your input is valuable.

Before making changes, start with `docs/architecture-onboarding.md`. It is the
single contributor entry point and explains which docs are mandatory versus
area-specific.

For the consolidated file-by-file maintenance catalog and update-sync rules,
use `docs/contributor-reference.md`.

## How to Contribute

### 1. Fork the Repository

Start by forking the repository to your own GitHub account. You can fork the project by clicking the "Fork" button on the top-right of the [repository page](https://github.com/AICyberGuardian/storycraftr-next).

### 2. Clone the Forked Repository

After forking, clone the repository to your local machine:

```bash
git clone https://github.com/AICyberGuardian/storycraftr-next.git
cd storycraftr-next
```

### 3. Create a New Branch

Create a new branch for your feature or bug fix:

```bash
git checkout -b feature/my-feature-name
```

### 4. Make Your Changes

Implement your feature, fix a bug, or improve documentation. Ensure that your changes are consistent with the coding style and structure of the project. If you are adding a new feature, make sure to add corresponding documentation or comments where necessary.

### 5. Test Your Changes

If applicable, make sure your changes pass all tests. You can run the tests locally using:

```bash
# Example if we have a test suite
poetry run pytest
```

If there are no formal tests in place, please test your changes to the best of your ability.

### 6. Commit Your Changes

Before committing, you must run formatting and all repository hooks.

Required pre-commit sequence:

```bash
poetry run black .
poetry run pre-commit run --all-files
git add -A
```

If pre-commit modifies files, stage again and re-run hooks until they pass.

Security and hygiene requirements:

- Never commit secrets (API keys, tokens, passwords, credentials).
- If a test fixture intentionally contains a fake secret-like value, use `# nosec B105  # pragma: allowlist secret` on that assignment line.
- Remove Windows metadata files such as `*:Zone.Identifier` before committing.
- Do not bypass hooks with `--no-verify` in normal development.

detect-secrets guidance:

- `detect-secrets` may flag example credential strings used in docs/scripts.
- Keep those examples inline-allowlisted instead of removing hooks or weakening checks.
- Use `# pragma: allowlist secret` on known-safe examples.
- Never disable hooks with `--no-verify` except true emergencies that are later corrected in follow-up commits.

Use Semantic Commit Messages to make your changes clearer and more organized. The format is:

```bash
<type>(<scope>): <description>
```

- **Type**: Describes the kind of change. For example: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`.
- **Scope**: The part of the project the change affects (optional). For example: `worldbuilding`, `outline`, `chapters`.
- **Description**: A brief explanation of the change.

Examples:

- Adding a new feature:
  ```bash
  git commit -m "feat(worldbuilding): add new geography prompt handling"
  ```
- Fixing a bug:

  ```bash
  git commit -m "fix(outline): correct plot points generation bug"
  ```

- Updating documentation:
  ```bash
  git commit -m "docs: update README with new installation instructions"
  ```

Make sure to commit often with meaningful messages to keep track of your changes effectively.

Optional helper script:

```bash
./scripts/dev_commit.sh -m "feat(scope): clear message"
```

This script runs formatting + pre-commit + staging before `git commit`.

### 7. Push Your Changes

Push your branch to GitHub:

```bash
git push origin feature/my-feature-name
```

### 8. Open a Pull Request

Go to the original repository on GitHub and open a pull request from your forked branch. Provide a detailed description of your changes and explain the problem you’re solving or the feature you’re adding.

### 9. Collaborate and Improve

Once you've submitted your pull request, be open to feedback from maintainers and other contributors. We may ask for changes, additional tests, or improvements to ensure the quality and stability of the project.

## Types of Contributions

We appreciate all kinds of contributions, including:

- **Bug Fixes**: If you find a bug, please let us know by opening an issue or fixing it yourself and submitting a pull request.
- **Feature Requests**: Suggest new features by opening an issue, or even better, implement the feature and open a pull request.
- **Documentation**: Improving the documentation is a great way to help other developers and users. This includes improving README, adding examples, and creating tutorials.
- **Refactoring**: If you see areas where the code could be improved, feel free to make those changes.
- **Tests**: If there is missing test coverage, feel free to add tests.

## Code of Conduct

Please be respectful and considerate in all interactions with the community. We strive to create an inclusive and welcoming environment for all contributors. See our [Code of Conduct](CODE_OF_CONDUCT.md) for more details.

## Issues and Bug Reports

If you encounter an issue with StoryCraftr, please report it using the [issue tracker](https://github.com/AICyberGuardian/storycraftr-next/issues). Include details such as your system environment, steps to reproduce the issue, and any error messages or logs.

## Need Help?

If you’re not sure where to start, feel free to ask questions by opening an issue or starting a discussion. We’re here to help!

---

Thank you for helping make **StoryCraftr** better! 🚀
