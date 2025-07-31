# Kitchen CLI Development Guidelines

## Project Overview
Kitchen is a sophisticated Python CLI tool for Kubernetes cluster management with Tailscale networking integration. Built with Poetry, Typer, and modern Python practices.

## Development History & Handover Process

### ALWAYS Read History First
Before making any changes, read the development history:
1. Check `.github/history/README.md` for current status
2. Read the latest numbered history file (highest number)
3. Understand what's working, what needs implementation

### Quick Context
- **SSH Infrastructure**: Production-ready persistent sessions
- **Master Verification**: Complete, tested with real infrastructure  
- **Next Task**: Convert worker node dry-run to actual implementation in `add_node()`

## Code Architecture & Standards

### Type System
Always use the established type aliases:
```python
CommandResult = tuple[int, str, str]       # (exit_code, stdout, stderr)
CommandList = list[tuple[str, str]]        # [(description, command), ...]
NodeStatus = dict[str, Union[bool, int, str, None]]  # Master node status
```

### SSH Session Pattern
Use persistent SSH sessions for multiple commands:
```python
results = run_interactive_ssh_session(host, user, commands, ssh_key, verbose)
```

### User Experience Requirements
- **Always ask for confirmation** before connecting to remote systems
- **Show descriptive operation names** instead of raw commands
- **Provide progress feedback** with emoji indicators
- **Handle errors gracefully** with actionable messages

## Development Focus

### Current Priority
Focus on `add_node()` function in `src/kitchen/k8s.py` lines 340-436:
- Dry-run shows exactly what to implement
- Replace planning with actual command execution
- Use existing SSH infrastructure

### Code Quality Standards
- **Type Hints**: Every function must have comprehensive annotations
- **120 char limit**: Use `# fmt: skip` for long strings
- **Constants**: No magic numbers, use named constants
- **Error Handling**: SSH timeouts, connection failures, edge cases

## Testing Infrastructure

Test with real infrastructure when possible:
```bash
# These work with 192.168.1.80, user: abja
poetry run kitchen k8s status
poetry run kitchen k8s nodes add --localhost --dry-run --master 192.168.1.80 --user abja
```
