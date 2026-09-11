# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.x     | :white_check_mark: |
| 0.x     | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability in Zeloo, please report it responsibly.

**Do NOT** open a public GitHub issue for security vulnerabilities.

### How to Report

1. Email the maintainers directly (preferred)
2. Use GitHub's [Private vulnerability reporting](https://github.com/Zeloo/Zeloo/security/advisories/new) feature

### What to Include

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

### Response Timeline

- **Initial response**: Within 48 hours
- **Assessment**: Within 7 days
- **Fix timeline**: Depends on severity (critical: 72h, high: 14 days, medium: 30 days)

## Security Design Principles

### Principle of Least Privilege

Zeloo components should request only the minimum permissions necessary. Credential access is controlled through the `CredentialPool`, which manages API keys without exposing them to tools or logs.

### Defense in Depth

Multiple layers of security controls:
1. **Input validation** — All tool inputs are validated before execution
2. **Context scanning** — Injected files are scanned for prompt injection patterns
3. **Output sanitization** — Sensitive data is masked in logs and responses
4. **Network isolation** — Tools can optionally run in isolated containers

### No Secret Storage in Code

- API keys must be stored in environment variables or a secrets manager
- Never commit `.env` files or any file containing real credentials
- Use `credential_pool.py` for dynamic credential management

### Sandboxed Execution

Tools that execute external code (shell, code execution) should:
- Run with minimal process permissions
- Have timeout limits enforced
- Have resource limits (memory, CPU) where possible
- Never run with root/administrator privileges

## Known Security Considerations

### Prompt Injection

Context files (AGENTS.md, .cursorrules, .Zeloo.md) are scanned before injection. Files containing known injection patterns are blocked and replaced with a safe placeholder.

### Credential Exposure

Zeloo never prints API keys in logs or error messages. The `CredentialPool` redacts keys in all output.

### Third-Party Dependencies

- All dependencies are pinned to exact versions (no version ranges)
- Dependencies are audited via `uv pip audit` and `ruff check`
- Known vulnerabilities trigger CI failure

### Multi-Tenant Isolation

When Zeloo runs as a multi-user gateway:
- Sessions are isolated by platform + user_id
- Profile directories ensure data separation
- Rate limiting prevents resource exhaustion

## Security Updates

Security updates are released as patch versions (e.g., 1.0.1) and announced through:
- GitHub Security Advisories
- Release notes

Users are encouraged to update promptly, especially after security-related releases.
