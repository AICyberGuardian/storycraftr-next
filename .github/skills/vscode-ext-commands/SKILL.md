---
name: vscode-ext-commands
description: 'Guidelines for contributing commands in VS Code extensions. Indicates naming convention, visibility, localization and other relevant attributes, following VS Code extension development guidelines, libraries and good practices'
---

# VS Code Extension Command Contribution

Guidelines for implementing commands in VS Code extensions following best practices and conventions.

## Command Types

### Regular Commands
- Accessible in Command Palette by default
- Must define `title` and `category`
- Use standard naming: `extension.commandName`
- Example: `storycraftr.outline`, `storycraftr.chapters`

### Side Bar Commands
- Start with underscore prefix: `_extension.command#sideBar`
- Must define an `icon`
- May have `enablement` rules
- Can be placed in `view/title` or `view/item/context`
- Include positioning metadata in menu contributions

## Command Definition

All commands require:
- **title**: User-friendly display name
- **category**: Logical grouping (e.g., "StoryCraftr")
- **command**: Unique identifier starting with extension ID
- **when**: Optional condition for visibility

## Naming Conventions

- Namespace with extension ID: `storycraftr.xxx`
- Use camelCase: `storycraftr.generateOutline`
- Keep names concise and descriptive
- Side bar: suffix with `#sideBar`

## Menu Placement

- Command Palette: Register with `when` clause
- View Container: Use `view/title` group
- View Items: Use `view/item/context` for specific file types
- Editor: Use `editor/context` for context menus

## Implementation Checklist

- [ ] Command has descriptive `title`
- [ ] Command has appropriate `category`
- [ ] Command ID follows naming convention
- [ ] Visibility rules (`when` clauses) are correct
- [ ] Icons are provided for Side Bar commands
- [ ] Menu placement is clear and logical
- [ ] Localization strings are prepared
