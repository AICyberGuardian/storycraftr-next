---
description: 'Automatically update README.md and documentation files when application code changes require documentation updates'
applyTo: '**/*.{md,js,mjs,cjs,ts,tsx,jsx,py,java,cs,go,rb,php,rs,cpp,c,h,hpp}'
---

# Update Documentation on Code Change

## Overview

Ensure documentation stays synchronized with code changes by automatically detecting when README.md,
API documentation, configuration guides, and other documentation files need updates based on code
modifications.

## Trigger Conditions

Automatically check if documentation updates are needed when:

- New features or functionality are added
- API endpoints, methods, or interfaces change
- Breaking changes are introduced
- Dependencies or requirements change
- Configuration options or environment variables are modified
- Installation or setup procedures change
- Command-line interfaces or scripts are updated
- Code examples in documentation become outdated

## Documentation Update Rules

### README.md Updates

**Always update README.md when:**

- Adding new features or capabilities
  - Add feature description to "Features" section
  - Include usage examples if applicable
  - Update table of contents if present

- Modifying installation or setup process
  - Update "Installation" or "Getting Started" section
  - Revise dependency requirements
  - Update prerequisite lists

- Adding new CLI commands or options
  - Document command syntax and examples
  - Include option descriptions and default values
  - Add usage examples

- Changing configuration options
  - Update configuration examples
  - Document new environment variables
  - Update config file templates

### API Documentation Updates

**Sync API documentation when:**

- New endpoints are added
  - Document HTTP method, path, parameters
  - Include request/response examples
  - Update OpenAPI/Swagger specs

- Endpoint signatures change
  - Update parameter lists
  - Revise response schemas
  - Document breaking changes

- Authentication or authorization changes
  - Update authentication examples
  - Revise security requirements
  - Update API key/token documentation

### Code Example Synchronization

**Verify and update code examples when:**

- Function signatures change
  - Update all code snippets using the function
  - Verify examples still compile/run
  - Update import statements if needed

- API interfaces change
  - Update example requests and responses
  - Revise client code examples
  - Update SDK usage examples

### Changelog Management

**Add changelog entries for:**

- New features (under "Added" section)
- Bug fixes (under "Fixed" section)
- Breaking changes (under "Changed" section with **BREAKING** prefix)
- Deprecated features (under "Deprecated" section)
- Security fixes (under "Security" section)

## Documentation Quality Standards

### Writing Guidelines

- Use clear, concise language
- Include working code examples
- Provide both basic and advanced examples
- Use consistent terminology
- Include error handling examples
- Document edge cases and limitations

### Code Example Format

    ```language
    // Include necessary imports/setup
    import { function } from 'package';

    // Complete, runnable example
    const result = function(parameter);
    console.log(result);
    ```

### API Documentation Format

    ### `functionName(param1, param2)`

    Brief description of what the function does.

    **Parameters:**
    - `param1` (type): Description of parameter
    - `param2` (type, optional): Description with default value

    **Returns:**
    - `type`: Description of return value

## Standard Documentation Files

Maintain these documentation files and update as needed:

- **README.md**: Project overview, quick start, basic usage
- **CHANGELOG.md**: Version history and user-facing changes
- **docs/**: Detailed documentation
- **examples/**: Working code examples and tutorials
