# Kitchen CLI Development Guidelines

## Project Overview
Kitchen is a sophisticated Python CLI tool for Kubernetes cluster management with Tailscale networking integration. Built with Poetry, Typer, and modern Python practices.

## Development History & Handover Process

### ALWAYS Read History First
Before making any changes, read the development history:
1. Check `.github/history/README.md` for current status
2. Read the latest numbered history file (highest number)
3. Understand what's working, what needs implementation
4. Focus on the next steps outlined in the latest file

### Debugging and issues
If you see issue you can fix it immediately, you don't need user interaction to validate that you need to fix, only on the architecture level you need to internact with user. 

### User Experience Requirements
- **Provide progress feedback** with emoji indicators
- **Handle errors gracefully** with actionable messages

### Code Quality Standards
- **Type Hints**: Every function must have comprehensive annotations
- **120 char limit**: Use `# fmt: skip` for long strings
- **Constants**: No magic numbers, use named constants
- **Error Handling**: SSH timeouts, connection failures, edge cases
- **Minimal External Dependencies**: Use only Python standard library, no new dependencies
- **Use Modules**: Organize code into modules for better maintainability.
## Testing Infrastructure

