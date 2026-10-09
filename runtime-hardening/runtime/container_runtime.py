"""Container runtime abstraction and isolation backends (ADR-001).

Provides an abstract :class:`ContainerRuntime` with concrete Docker/Podman
implementations driving the container engine CLI, plus:

* isolation backends (``runc`` / gVisor ``runsc`` / Kata-on-Firecracker),
* a seccomp profile generator built from the architecture spec,
* rootless execution with explicit user-namespace mapping.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from runtime.models import IsolationTier


class ContainerRuntimeError(RuntimeError):
    """Raised when a container engine operation fails."""


class ContainerRuntimeUnavailable(ContainerRuntimeError):
    """Raised when the configured container engine binary is not on PATH."""


# --------------------------------------------------------------------------- #
# Isolation backends
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class IsolationBackend:
    """Describes the engine-level invocation for one isolation tier."""

    tier: IsolationTier
    runtime_class: str
    engine_runtime: str | None
    requires_kvm: bool = False
    sandbox_binary: str | None = None
    security_options: tuple[str, ...] = ()

    def engine_args(self) -> list[str]:
        args: list[str] = []
        if self.engine_runtime is not None:
            args += ["--runtime", self.engine_runtime]
        for opt in self.security_options:
            args += ["--security-opt", opt]
        return args


ISOLATION_BACKENDS: dict[IsolationTier, IsolationBackend] = {
    IsolationTier.BASELINE_RUNC: IsolationBackend(
        tier=IsolationTier.BASELINE_RUNC,
        runtime_class="runc",
        engine_runtime=None,
        sandbox_binary="bwrap",
    ),
    IsolationTier.GVISOR_RUNSC: IsolationBackend(
        tier=IsolationTier.GVISOR_RUNSC,
        runtime_class="runsc",
        engine_runtime="runsc",
        security_options=("no-new-privileges:true",),
    ),
    IsolationTier.KATA_FC: IsolationBackend(
        tier=IsolationTier.KATA_FC,
        runtime_class="kata-fc",
        engine_runtime="kata-fc",
        requires_kvm=True,
    ),
    IsolationTier.GVISOR_NSJAIL: IsolationBackend(
        tier=IsolationTier.GVISOR_NSJAIL,
        runtime_class="runsc",
        engine_runtime="runsc",
        sandbox_binary="nsjail",
        security_options=("no-new-privileges:true",),
    ),
}


def select_isolation_backend(tier: IsolationTier, *, kvm_available: bool) -> IsolationBackend:
    """Select a backend for ``tier``, falling back when KVM is unavailable.

    Kata-on-Firecracker requires ``/dev/kvm``; when it is missing we fall back to
    the no-KVM strongest option (gVisor + inner nsjail) per ADR-001.
    """
    backend = ISOLATION_BACKENDS[tier]
    if backend.requires_kvm and not kvm_available:
        return ISOLATION_BACKENDS[IsolationTier.GVISOR_NSJAIL]
    return backend


def kvm_available(dev_kvm: Path = Path("/dev/kvm")) -> bool:
    """Return True when the host exposes a usable KVM device."""
    return dev_kvm.exists()


# --------------------------------------------------------------------------- #
# Seccomp profile generation
# --------------------------------------------------------------------------- #
DEFAULT_ALLOWED_SYSCALLS: tuple[str, ...] = (
    "accept",
    "arch_prctl",
    "bind",
    "brk",
    "capget",
    "capset",
    "chdir",
    "clone",
    "clone3",
    "close",
    "connect",
    "dup",
    "dup2",
    "dup3",
    "epoll_create1",
    "epoll_ctl",
    "epoll_pwait",
    "epoll_wait",
    "execve",
    "execveat",
    "exit",
    "exit_group",
    "fchmod",
    "fchmodat",
    "fchown",
    "fchownat",
    "fcntl",
    "fdatasync",
    "fstat",
    "fstatfs",
    "fsync",
    "ftruncate",
    "futex",
    "getcwd",
    "getdents64",
    "getegid",
    "geteuid",
    "getgid",
    "getpeername",
    "getpid",
    "getppid",
    "getrandom",
    "getsockname",
    "getsockopt",
    "gettid",
    "getuid",
    "ioctl",
    "listen",
    "lseek",
    "madvise",
    "mkdir",
    "mkdirat",
    "mmap",
    "mprotect",
    "mremap",
    "munmap",
    "nanosleep",
    "newfstatat",
    "open",
    "openat",
    "pipe",
    "pipe2",
    "poll",
    "ppoll",
    "prctl",
    "pread64",
    "prlimit64",
    "pwrite64",
    "read",
    "readlink",
    "readlinkat",
    "readv",
    "recvfrom",
    "recvmsg",
    "rename",
    "renameat",
    "renameat2",
    "restart_syscall",
    "rt_sigaction",
    "rt_sigprocmask",
    "rt_sigreturn",
    "sched_getaffinity",
    "sched_yield",
    "sendmsg",
    "sendto",
    "set_robust_list",
    "setsockopt",
    "set_tid_address",
    "shutdown",
    "sigaltstack",
    "socket",
    "socketpair",
    "statx",
    "tgkill",
    "uname",
    "unlink",
    "unlinkat",
    "wait4",
    "waitid",
    "write",
    "writev",
)


@dataclass
class SeccompProfileGenerator:
    """Builds an OCI seccomp JSON profile from an architecture spec.

    The generated profile is default-deny (``SCMP_ACT_ERRNO``) and allows only
    the syscalls in :attr:`allowed_syscalls`. ``EPERM`` is returned for blocked
    calls rather than killing the process, matching ``RuntimeDefault`` style.
    """

    allowed_syscalls: tuple[str, ...] = DEFAULT_ALLOWED_SYSCALLS
    default_action: str = "SCMP_ACT_ERRNO"
    architectures: tuple[str, ...] = ("SCMP_ARCH_X86_64", "SCMP_ARCH_X86")

    def generate(self) -> dict[str, Any]:
        return {
            "defaultAction": self.default_action,
            "defaultErrnoRet": 1,
            "architectures": list(self.architectures),
            "syscalls": [
                {
                    "names": sorted(self.allowed_syscalls),
                    "action": "SCMP_ACT_ALLOW",
                }
            ],
        }

    def write(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.generate(), indent=2), encoding="utf-8")
        return target


# --------------------------------------------------------------------------- #
# Rootless / user namespace mapping
# --------------------------------------------------------------------------- #
@dataclass
class UsernsMapping:
    """A single uid/gid map line (``inside outside count``)."""

    inside: int
    outside: int
    count: int

    def render(self) -> str:
        return f"{self.inside} {self.outside} {self.count}"


@dataclass
class RootlessConfig:
    """User-namespace mapping for rootless container execution."""

    enabled: bool = True
    uid_map: list[UsernsMapping] = field(default_factory=lambda: [UsernsMapping(0, 100000, 65536)])
    gid_map: list[UsernsMapping] = field(default_factory=lambda: [UsernsMapping(0, 100000, 65536)])
    run_as_non_root: bool = True
    run_as_user: int = 1000
    keep_id: bool = True

    def engine_args(self) -> list[str]:
        if not self.enabled:
            return []
        args = ["--userns=keep-id"] if self.keep_id else []
        args.append(f"--user={self.run_as_user}")
        return args


# --------------------------------------------------------------------------- #
# Container runtime abstraction
# --------------------------------------------------------------------------- #
@dataclass
class ContainerInfo:
    container_id: str
    state: str
    image: str | None = None
    runtime: str | None = None


class ContainerRuntime(ABC):
    """Abstract container engine interface."""

    name: str = "abstract"
    binary: str = ""

    def available(self) -> bool:
        """Return True when the engine binary is on PATH."""
        return shutil.which(self.binary) is not None

    def _require(self) -> None:
        if not self.available():
            raise ContainerRuntimeUnavailable(f"{self.binary!r} not found on PATH")

    def _run(self, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        self._require()
        proc = subprocess.run(  # noqa: S603 - fixed binary, list args
            [self.binary, *args],
            capture_output=True,
            text=True,
            check=False,
        )
        if check and proc.returncode != 0:
            raise ContainerRuntimeError(
                f"{self.binary} {' '.join(args)} failed ({proc.returncode}): {proc.stderr.strip()}"
            )
        return proc

    @abstractmethod
    def create_args(
        self,
        *,
        image: str,
        name: str,
        backend: IsolationBackend,
        rootless: RootlessConfig,
        seccomp_profile: str | Path | None,
        limits: list[str],
        env: dict[str, str],
        detach: bool = True,
    ) -> list[str]:
        """Return the engine arguments (excluding the binary) to create a container."""

    @abstractmethod
    def create(self, args: list[str]) -> ContainerInfo:
        """Create (and start) a container and return its info."""

    @abstractmethod
    def stop(self, container_id: str, grace_seconds: int = 30) -> None: ...

    @abstractmethod
    def remove(self, container_id: str, force: bool = False) -> None: ...

    @abstractmethod
    def pause(self, container_id: str) -> None: ...

    @abstractmethod
    def resume(self, container_id: str) -> None: ...

    @abstractmethod
    def inspect(self, container_id: str) -> dict[str, Any]: ...

    @abstractmethod
    def logs(self, container_id: str, tail: int = 200) -> str: ...


class CliContainerRuntime(ContainerRuntime):
    """Shared CLI mechanics for docker/podman-style engines."""

    _readonly_flags = ["--read-only"]
    _capdrop_flags = ["--cap-drop=ALL"]
    _no_new_privileges = ["--security-opt=no-new-privileges:true"]

    def create_args(
        self,
        *,
        image: str,
        name: str,
        backend: IsolationBackend,
        rootless: RootlessConfig,
        seccomp_profile: str | Path | None,
        limits: list[str],
        env: dict[str, str],
        detach: bool = True,
    ) -> list[str]:
        args: list[str] = ["run", "--name", name]
        if detach:
            args.append("-d")
        args += ["--init"]
        args += self._readonly_flags
        args += self._capdrop_flags
        args += self._no_new_privileges
        args += backend.engine_args()
        args += rootless.engine_args()
        if seccomp_profile is not None and str(seccomp_profile) != "RuntimeDefault":
            args += ["--security-opt", f"seccomp={seccomp_profile}"]
        args += limits
        for key, value in env.items():
            args += ["-e", f"{key}={value}"]
        args.append(image)
        return args

    def create(self, args: list[str]) -> ContainerInfo:
        proc = self._run(args)
        container_id = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
        return ContainerInfo(container_id=container_id, state="running", image=args[-1])

    def stop(self, container_id: str, grace_seconds: int = 30) -> None:
        self._run(["stop", "-t", str(grace_seconds), container_id], check=False)

    def remove(self, container_id: str, force: bool = False) -> None:
        args = ["rm"]
        if force:
            args.append("-f")
        args.append(container_id)
        self._run(args, check=False)

    def pause(self, container_id: str) -> None:
        self._run(["pause", container_id])

    def resume(self, container_id: str) -> None:
        self._run(["unpause", container_id])

    def inspect(self, container_id: str) -> dict[str, Any]:
        proc = self._run(["inspect", container_id])
        data = json.loads(proc.stdout)
        if not isinstance(data, list) or not data:
            raise ContainerRuntimeError(f"no inspect data for {container_id!r}")
        first = data[0]
        if not isinstance(first, dict):
            raise ContainerRuntimeError(f"malformed inspect data for {container_id!r}")
        return first

    def logs(self, container_id: str, tail: int = 200) -> str:
        proc = self._run(["logs", "--tail", str(tail), container_id], check=False)
        return proc.stdout


class DockerRuntime(CliContainerRuntime):
    name = "docker"
    binary = "docker"


class PodmanRuntime(CliContainerRuntime):
    name = "podman"
    binary = "podman"
    _readonly_flags = ["--read-only"]
    _no_new_privileges = ["--security-opt=no-new-privileges"]


def build_runtime(name: str) -> ContainerRuntime:
    """Factory returning a runtime implementation by name."""
    normalized = name.lower()
    if normalized == "docker":
        return DockerRuntime()
    if normalized == "podman":
        return PodmanRuntime()
    raise ValueError(f"unknown container runtime {name!r}")
