---
name: pytest-coverage
description: 'Run pytest tests with coverage, discover lines missing coverage, and increase coverage to 100%.'
---

# Pytest Coverage

Achieve comprehensive test coverage for your Python projects.

## Overview

The goal is to ensure all lines of code are tested, providing confidence that edge cases are handled and regressions are caught early.

## Key Steps

1. **Run coverage report**
   ```bash
   pytest --cov --cov-report=annotate:cov_annotate
   ```

2. **Identify gaps** - Review files in `cov_annotate/` to find uncovered lines (marked with `!`)

3. **Write tests** - Add tests covering the missing lines

4. **Iterate** - Re-run coverage until 100% is achieved

## Coverage for Specific Modules

```bash
pytest --cov=your_module_name --cov-report=annotate:cov_annotate
```

## Specific Test Files

```bash
pytest tests/test_your_module.py --cov=your_module_name --cov-report=annotate:cov_annotate
```

## Workflow

- Module files with 100% coverage: No action needed
- Module files with <100% coverage: Review `cov_annotate/` files
- Lines marked with `!`: Write tests to cover these paths
- Keep running until all coverage goals are met
