# Kitchen CLI - TODO List

## High Priority

### Node Join Token Validation
- [ ] Implement token validation for node join command
  - Check if the join token is still valid before attempting to join
  - Verify token hasn't expired
  - Validate token format and structure
  - Provide clear error messages if token is invalid or expired
  - Consider adding a `--force` flag to skip validation if needed

## Medium Priority

### Node Manager Architecture Improvement
- [ ] Convert node-manager from Deployment to DaemonSet
  - Run one node-manager pod per node for accurate connectivity monitoring
  - Enable per-node monitoring of connectivity to all other nodes
  - Improve database connection efficiency by distributing load
  - Update RBAC permissions if needed
  - Adjust resource limits for single-pod-per-node model
  - Consider node-local storage for temporary data
  - Update anti-affinity rules (no longer needed with DaemonSet)

- [ ] Add comprehensive error handling for edge cases
- [ ] Improve progress feedback with more granular status updates
- [ ] Add retry logic for transient failures

## Low Priority

- [ ] Add configuration file support for common settings
- [ ] Implement dry-run mode for destructive operations
- [ ] Add shell completion scripts (bash, zsh, fish)

## Completed

- [x] Rename KubernetesNodeClient to K8sClient
- [x] Add Sentry DSN support to node-manager deploy command
- [x] Fix lint errors in exception handlers

---

## Notes

### Token Validation Implementation Ideas
```python
# Potential approach for token validation
def validate_join_token(token: str, master_ip: str) -> tuple[bool, str]:
    """
    Validate if a Kubernetes join token is still valid.
    
    Returns:
        tuple: (is_valid, error_message)
    """
    # 1. Check token format (should be xxxx.yyyyyyyyyyyyyy)
    # 2. SSH to master and run: kubeadm token list
    # 3. Check if token exists and hasn't expired
    # 4. Return validation result
    pass
```

### References
- Kubernetes join token format: `[a-z0-9]{6}\.[a-z0-9]{16}`
- Token default TTL: 24 hours
- Command to check tokens: `kubeadm token list`
