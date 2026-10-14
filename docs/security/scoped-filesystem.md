# Scoped filesystem boundary for native agent tools (issue #19)

**Status:** staged, filesystem-only implementation; **not** approval for executing
untrusted arbitrary shell, Git, network or Python tool calls. It does not close
the broader Issue #5 or prove the autonomous SDLC acceptance in Issue #11.

## Contract

The **control plane** supplies an existing, trusted workspace directory and a
normalized per-role tool policy. The model may supply only a relative resource
path and UTF-8 text; it cannot change the workspace root, the policy or the
size limits. `ScopedFilesystemExecutor` exposes only `read_text` and
`write_text`.

Each request is rejected before any I/O unless `fs_read` or `fs_write` is
explicitly permitted for the effective absolute path. Denials are not executed.
The executor never shells out, starts subprocesses or invokes LLMs.

On Linux, every ancestor is opened using directory FDs + `O_DIRECTORY |
O_NOFOLLOW`, and regular-file reads use `O_NOFOLLOW`; these prevent following
a symlink even when the path changes after lexical validation. Writes use an
exclusive same-directory temporary regular file and `os.replace` to avoid
modifying an inode outside the workspace even on a concurrent destination swap.
Non-regular file reads (including FIFOs/sockets) and hard-linked files are
rejected. Common control-plane directories (`.git`, `.ssh`, `.hermes`, etc.),
`.env*`, and private key extensions are denied.

### Example (trusted caller only)

```python
from agent_management.scoped_fs import ScopedFilesystemExecutor

executor = ScopedFilesystemExecutor(
    "/srv/workspaces/task-123",
    {
        "fs_read": ["/srv/workspaces/task-123/src/**"],
        "fs_write": ["/srv/workspaces/task-123/out/**"],
    },
    max_read_bytes=1_048_576,
    max_write_bytes=1_048_576,
)
source = executor.read_text("src/main.py")
executor.write_text("out/report.txt", "verified result")
```

## Remaining boundary restrictions

- **Windows:** this implementation rejects initialization. Do **not** replace
  it with naive `Path.resolve` string checks. Implement and test native
  Windows handle-based no-reparse traversal separately before enabling.
- **Trusted workspace provisioning is required:** do not give agents the
  ability to bind-mount or remount arbitrary host directories inside workspace;
  kernel/container isolation, UID controls, hardlink/mount protection and
  host Docker socket restrictions remain separate security gates.
- **No tool dispatch:** function-call assembly in OpenRouter streaming does not
  authorize running file operations. The future native tool executor must route
  only allowlisted function names to this API and independently validate
  JSON schema, limits, correlation IDs and results.
- **No generic script execution:** shell, Git and HTTPS require separate
  vetted tool adapters with deny-before-side-effect security tests (#20).
- **Atomic files, not transactions:** one file replacement is atomic; multiple
  file edits, worktree commits and task completion require a higher-level
  orchestrator plus Contract Gate.

## Reproduce

```bash
cd agent-management
python -m pytest tests/test_scoped_fs.py -q
```

On Linux, tests exercise traversal, sibling prefixes, parent/final symlinks,
FIFOs, hardlinks, restricted names, size limits, write atomicity and policy
denial before any `os.open`. The full CI and Quality Gate must also pass.
