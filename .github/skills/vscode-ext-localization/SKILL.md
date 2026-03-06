---
name: vscode-ext-localization
description: 'Guidelines for proper localization of VS Code extensions, following VS Code extension development guidelines, libraries and good practices'
---

# VS Code Extension Localization

Guidelines for properly localizing every aspect of VS Code extensions.

## Localization Approaches

### 1. Configuration (Settings, Commands, Menus, Views, Walkthroughs)
- Create `package.nls.LANGID.json` files
- Example: `package.nls.pt-br.json` for Brazilian Portuguese
- Translate all `title`, `description`, and user-facing strings

### 2. Walkthrough Content
- Create localized Markdown files
- Example: `walkthrough/someStep.pt-br.md`
- Translate narrative content and instructions

### 3. Source Code Messages
- Create `bundle.l10n.LANGID.json` files
- Example: `bundle.l10n.pt-br.json` for Brazilian Portuguese
- Translate user-facing strings in TypeScript/JavaScript

## Process

When adding new localizable resources:

1. Create the resource in the default language
2. For each supported language:
   - Create language-specific configuration/content file
   - Translate all user-facing strings
   - Maintain consistency with existing terminology

## Supported Language Codes

- `pt-br`: Brazilian Portuguese
- `es`: Spanish
- `fr`: French
- `de`: German
- `ja`: Japanese
- `zh-cn`: Simplified Chinese
- And others as needed

## Best Practices

- Keep translations consistent with existing glossary
- Review translations for clarity and cultural appropriateness
- Test localized UI to ensure proper display
- Maintain translation files in sync with source changes
- Document terminology decisions in translation notes

## Files to Localize

- `package.json`: Commands, settings, views, walkthroughs
- Extension code: User messages, error strings, status updates
- Documentation: Walkthrough content, tutorials
