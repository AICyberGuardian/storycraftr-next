---
name: refactor
description: 'Surgical code refactoring to improve maintainability without changing behavior. Covers extracting functions, renaming variables, breaking down god functions, improving type safety, eliminating code smells, and applying design patterns. Less drastic than repo-rebuilder; use for gradual improvements.'
license: MIT
---

# Refactor

## Overview

Improve code structure and readability without changing external behavior. Refactoring is gradual evolution, not revolution. Use this for improving existing code, not rewriting from scratch.

## When to Use

Use this skill when:

- Code is hard to understand or maintain
- Functions/classes are too large
- Code smells need addressing
- Adding features is difficult due to code structure
- User asks "clean up this code", "refactor this", "improve this"

---

## Refactoring Principles

### The Golden Rules

1. **Behavior is preserved** - Refactoring doesn't change what the code does, only how
2. **Small steps** - Make tiny changes, test after each
3. **Version control is your friend** - Commit before and after each safe state
4. **Tests are essential** - Without tests, you're not refactoring, you're editing
5. **One thing at a time** - Don't mix refactoring with feature changes

### When NOT to Refactor

```
- Code that works and won't change again (if it ain't broke...)
- Critical production code without tests (add tests first)
- When you're under a tight deadline
- "Just because" - need a clear purpose
```

---

## Common Code Smells & Fixes

### 1. Long Method/Function

Extract large methods into smaller, focused functions with single responsibilities.

### 2. Duplicated Code

Consolidate duplicated logic into shared functions or utilities.

### 3. Large Class/Module

Break large classes into smaller classes, each with single responsibility.

### 4. Long Parameter List

Group related parameters into objects or interfaces to reduce parameter count.

### 5. Feature Envy

Move methods to the objects that actually own the data they operate on.

### 6. Primitive Obsession

Use domain types instead of primitives to add semantic meaning.

### 7. Magic Numbers/Strings

Extract magic values into named constants to improve readability.

### 8. Nested Conditionals

Use guard clauses and early returns to flatten conditional structure.

### 9. Dead Code

Remove unused functions, imports, and commented-out code.

### 10. Inappropriate Intimacy

Use proper encapsulation instead of reaching deep into other objects.

---

## Refactoring Strategies

### Extract Method
- Break large methods into smaller helper functions
- Each function should do one thing well
- Use clear, descriptive names

### Rename for Clarity
- Use intention-revealing names
- Make code self-documenting
- Update all references consistently

### Introduce Types
- Replace primitive types with meaningful domain types
- Add proper type annotations
- Enable better compiler/IDE checking

### Apply Design Patterns
- Use Strategy for conditional behavior variation
- Use Chain of Responsibility for validation chains
- Use Factory for complex object creation
- Use Decorator for adding responsibilities

### Simplify Conditionals
- Replace nested if-else with guard clauses
- Use switch statements for cleaner dispatch
- Extract boolean logic into named variables

---

## Safe Refactoring Process

```
1. PREPARE
   - Ensure tests exist (write them if missing)
   - Commit current state
   - Create feature branch

2. IDENTIFY
   - Find the code smell to address
   - Understand what the code does
   - Plan the refactoring

3. REFACTOR (small steps)
   - Make one small change
   - Run tests
   - Commit if tests pass
   - Repeat

4. VERIFY
   - All tests pass
   - Manual testing if needed
   - Performance unchanged or improved

5. CLEAN UP
   - Update comments
   - Update documentation
   - Final commit
```

---

## Refactoring Checklist

### Code Quality

- [ ] Functions are small (< 50 lines)
- [ ] Functions do one thing
- [ ] No duplicated code
- [ ] Descriptive names (variables, functions, classes)
- [ ] Minimal parameters per function
- [ ] Clear dependencies

### Type Safety

- [ ] No implicit types (use explicit annotations)
- [ ] No `any` types without justification
- [ ] Proper error handling
- [ ] Clear interfaces and contracts

### Testing

- [ ] All tests still pass
- [ ] No behavior change detected
- [ ] Edge cases covered

### Documentation

- [ ] Comments explain "why", not "what"
- [ ] Updated docstrings/JSDoc
- [ ] Architecture documentation current
