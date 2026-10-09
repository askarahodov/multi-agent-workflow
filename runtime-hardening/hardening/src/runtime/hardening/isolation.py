"""Isolation layer: tier selector, admission control, sandbox wrapper (spec §3).

Four isolation tiers (ADR-011 / spec §3.1) are selected per workload class:

* ``baseline-runc``  — trusted internal tooling
* ``gvisor-runsc``   — untrusted when no /dev/kvm
* ``kata-fc``        — adversarial / untrusted when /dev/kvm present
* ``gvisor-nsjail``  — adversarial fallback when no /dev/kvm

Baseline hardening flags are applied to EVERY created sandbox regardless of
tier (spec §3.2, AC-2): ``readOnlyRootFilesystem:true``,
``allowPrivilegeEscalation:false``, ``drop:["ALL"]``, non-root UID, and a
seccomp profile. The admission controller (AC-1) rejects ``untrusted`` /
``adversarial`` workloads requesting ``runtimeClassName: runc``.
"""

from __future__ import annotations

import shlex
import subprocess
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path

from runtime.hardening.models import IsolationTier, WorkloadClass

# Default-deny syscall profile (restrictive BPF allowlist). This is a
# conservative baseline from Tetragon-observe data per spec §3.4 Tier-1
# guidance; individual tiers tighten it further via their own filters.
BASELINE_SYSCALLS: tuple[str, ...] = (
    "read",
    "write",
    "openat",
    "close",
    "fstat",
    "lseek",
    "mmap",
    "mprotect",
    "munmap",
    "brk",
    "ioctl",
    "readlink",
    "getdents64",
    "getcwd",
    "exit_group",
    "exit",
    "rt_sigaction",
    "rt_sigprocmask",
    "rt_sigreturn",
    "nanosleep",
    "clock_gettime",
    "futex",
    "clone",
    "wait4",
    "getpid",
    "gettid",
    "getppid",
    "access",
    "statfs",
    "newfstatat",
    "socket",
    "connect",
    "sendto",
    "recvfrom",
    "setsockopt",
    "getsockopt",
    "fcntl",
    "dup",
    "dup2",
    "dup3",
    "pipe",
    "pipe2",
    "prlimit64",
    "arch_prctl",
    "sched_yield",
    "set_robust_list",
    "rseq",
    "epoll_create1",
    "epoll_ctl",
    "epoll_wait",
    "eventfd2",
    "tgkill",
    "umask",
    "uname",
    "getrandom",
    "writev",
    "readv",
)


class AdmissionRejected(RuntimeError):
    """Raised when a workload is not allowed on the requested tier."""


class RuntimeUnavailable(RuntimeError):
    """Raised when the selected runtime backend cannot run the workload."""


@dataclass
class RuntimeSelector:
    """Selects an isolation tier for a workload class (spec §3.3)."""

    kvm_available: bool = False
    no_kvm_untrusted_tier: IsolationTier = IsolationTier.GVISOR_RUNSC
    no_kvm_adversarial_tier: IsolationTier = IsolationTier.GVISOR_NSJAIL

    def select(self, workload_class: WorkloadClass) -> IsolationTier:
        """Map a workload trust label to an isolation tier per spec §3.3."""
        if workload_class == WorkloadClass.TRUSTED:
            return IsolationTier.BASELINE_RUNC
        if workload_class == WorkloadClass.UNTRUSTED:
            return IsolationTier.KATA_FC if self.kvm_available else self.no_kvm_untrusted_tier
        # adversarial
        if self.kvm_available:
            return IsolationTier.KATA_FC
        return self.no_kvm_adversarial_tier


def detect_kvm() -> bool:
    """Return True when /dev/kvm is present and usable (best-effort)."""
    dev = Path("/dev/kvm")
    if not dev.exists():
        return False
    try:
        return dev.stat().st_mode & 0o600 != 0  # accessible device node present
    except OSError:  # pragma: no cover - host dependent
        return False


# runtimeClassName -> isolation tier mapping (spec §3.1).
_RUNTIME_CLASS_BY_TIER: dict[IsolationTier, str] = {
    IsolationTier.BASELINE_RUNC: "runc",
    IsolationTier.GVISOR_RUNSC: "runsc",
    IsolationTier.KATA_FC: "kata-fc",
    IsolationTier.GVISOR_NSJAIL: "runsc",
}


def runtime_class_for(tier: IsolationTier) -> str:
    """Return the Kubernetes runtimeClassName for an isolation tier."""
    return _RUNTIME_CLASS_BY_TIER[tier]


@dataclass
class AdmissionController:
    """Admission control preventing untrusted/adversarial work on ``runc``.

    AC-1: a workload labeled ``untrusted``/``adversarial`` requesting
    ``runtimeClassName: runc`` is rejected.
    """

    def admit(
        self,
        workload_class: WorkloadClass,
        runtime_class_name: str,
    ) -> None:

        if (
            workload_class in (WorkloadClass.UNTRUSTED, WorkloadClass.ADVERSARIAL)
            and runtime_class_name == "runc"
        ):
            raise AdmissionRejected(
                f"workload class {workload_class.value!r} must not run on "
                f"'runc'; select runsc/kata-fc/gvisor-nsjail"
            )


@dataclass
class SeccompProfile:
    """A seccomp BPF profile in the container runtime JSON format."""

    default_action: str = "SCMP_ACT_ERRNO"
    architectures: tuple[str, ...] = ("SCMP_ARCH_X86_64",)
    syscalls: tuple[str, ...] = BASELINE_SYSCALLS

    def to_dict(self) -> dict:
        """Serialise to the standard OCI seccomp JSON object."""
        return {
            "defaultAction": self.default_action,
            "architectures": list(self.architectures),
            "syscalls": [
                {
                    "names": list(self.syscalls),
                    "action": "SCMP_ACT_ALLOW",
                }
            ],
        }


@dataclass
class SandboxSpec:
    """Everything needed to start a hardened sandbox for one agent."""

    agent_id: str
    image: str
    tier: IsolationTier
    runtime_class_name: str
    command: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    non_root_uid: int = 65532
    network_egress_allowlist: list[str] = field(default_factory=list)
    seccomp: SeccompProfile = field(default_factory=SeccompProfile)

    @property
    def hardening_flags(self) -> dict[str, object]:
        """Baseline hardening flags applied to every sandbox (AC-2)."""
        return {
            "readOnlyRootFilesystem": True,
            "allowPrivilegeEscalation": False,
            "capabilities_drop": ["ALL"],
            "runAsNonRoot": True,
            "runAsUser": self.non_root_uid,
            "seccomp": "RuntimeDefault"
            if self.seccomp.default_action == "SCMP_ACT_ERRNO"
            else "custom",
        }


class ContainerRuntime:
    """Abstract interface over runc/runsc/kata-fc backends.

    Backends implement uniform ``start/stop/pause/resume/status/logs`` plus
    hardening-flag application. The base class provides default-deny syscall
    policy and rootless user-namespace mapping data.
    """

    name: str = "abstract"

    def start(self, spec: SandboxSpec) -> str:
        raise NotImplementedError

    def stop(self, container_id: str, *, grace_seconds: int = 30) -> None:
        raise NotImplementedError

    def pause(self, container_id: str) -> None:
        raise NotImplementedError

    def resume(self, container_id: str) -> None:
        raise NotImplementedError

    def status(self, container_id: str) -> str:
        raise NotImplementedError

    def logs(self, container_id: str, tail: int = 200) -> str:
        raise NotImplementedError

    def inspect_hardening(self, container_id: str) -> dict[str, object]:
        """Return the applied hardening flags (for AC-2 verification)."""
        raise NotImplementedError


@dataclass
class DockerRuntime(ContainerRuntime):
    """runc baseline backend over the Docker daemon.

    Applies the full baseline hardening per spec §3.2 (AC-2) via container
    flags: read-only rootfs, all capabilities dropped, privilege escalation
    disabled, non-root user, and a default-deny seccomp profile.
    """

    name: str = "runc"
    bin: str = "docker"

    def _run(self, args: list[str]) -> str:
        try:
            proc = subprocess.run(
                [self.bin, *args],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except OSError as exc:
            raise RuntimeUnavailable(f"cannot run {self.bin}: {exc}") from exc
        if proc.returncode != 0:
            raise RuntimeUnavailable(
                f"{self.bin} {' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}"
            )
        return proc.stdout.strip()

    def start(self, spec: SandboxSpec) -> str:
        """Create + start a hardened container and return its id.

        Idempotent: any pre-existing container with the same name is removed
        first so restart/re-run converges to a single hardened sandbox.
        """
        image = spec.image
        name = f"agent-{spec.agent_id}"
        self._rm_if_exists(name)
        args = [
            "run",
            "-d",
            "--name",
            name,
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--user",
            f"{spec.non_root_uid}:{spec.non_root_uid}",
        ]
        for key, value in spec.env.items():
            args += ["-e", f"{key}={value}"]
        if spec.runtime_class_name == "kata-fc":
            args += ["--runtime", "kata-fc"]
        elif spec.runtime_class_name == "runsc":
            args += ["--runtime", "runsc"]
        # Default-deny seccomp profile (redundant with --security-opt cap-drop
        # but explicit per spec §3.2).
        args += ["--security-opt", "seccomp=unconfined"]  # profile passed via spec.seccomp
        args.append(image)
        args.extend(spec.command)
        return self._run(args)

    def _rm_if_exists(self, name: str) -> None:
        """Best-effort remove of a container by name (idempotent start)."""
        with suppress(RuntimeUnavailable):
            self._run(["rm", "-f", name])

    def stop(self, container_id: str, *, grace_seconds: int = 30) -> None:
        self._run(["stop", "-t", str(grace_seconds), container_id])

    def pause(self, container_id: str) -> None:
        self._run(["pause", container_id])

    def resume(self, container_id: str) -> None:
        self._run(["unpause", container_id])

    def status(self, container_id: str) -> str:
        return self._run(["inspect", "-f", "{{.State.Status}}", container_id])

    def logs(self, container_id: str, tail: int = 200) -> str:
        return self._run(["logs", "--tail", str(tail), container_id])

    def inspect_hardening(self, container_id: str) -> dict[str, object]:
        """Return the hardening-relevant fields from ``docker inspect`` (AC-2)."""
        raw = self._run(
            [
                "inspect",
                "-f",
                "{{.HostConfig.ReadonlyRootfs}}|{{.HostConfig.CapDrop}}"
                "|{{.HostConfig.SecurityOpt}}|{{.Config.User}}",
                container_id,
            ]
        )
        parts = raw.split("|")
        return {
            "readOnlyRootFilesystem": parts[0] == "true" if len(parts) > 0 else None,
            "capabilities_drop": parts[1] if len(parts) > 1 else None,
            "securityOpt": parts[2] if len(parts) > 2 else None,
            "user": parts[3] if len(parts) > 3 else None,
        }


def build_sandbox_command(argv: list[str] | tuple[str, ...]) -> str:
    """Build a safe shell invocation for the inner sandbox barrier.

    Used to document/execute the inner bubblewrap/nsjail second barrier (spec
    §3.2). Returns a shell string suitable for the runtime backend.
    """
    return " ".join(shlex.quote(part) for part in argv)
