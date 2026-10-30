"""Unit tests for the isolation layer: selector, admission, sandbox wrapper (spec §3)."""

from __future__ import annotations

from runtime.hardening.isolation import (
    AdmissionController,
    AdmissionRejected,
    DockerRuntime,
    RuntimeSelector,
    RuntimeUnavailable,
    SandboxSpec,
    SeccompProfile,
    runtime_class_for,
)
from runtime.hardening.models import IsolationTier, WorkloadClass


def test_selector_trusted_to_baseline_runc() -> None:
    selector = RuntimeSelector(kvm_available=False)
    assert selector.select(WorkloadClass.TRUSTED) == IsolationTier.BASELINE_RUNC


def test_selector_untrusted_no_kvm_gvisor_runsc() -> None:
    selector = RuntimeSelector(kvm_available=False)
    assert selector.select(WorkloadClass.UNTRUSTED) == IsolationTier.GVISOR_RUNSC


def test_selector_untrusted_with_kvm_kata_fc() -> None:
    selector = RuntimeSelector(kvm_available=True)
    assert selector.select(WorkloadClass.UNTRUSTED) == IsolationTier.KATA_FC


def test_selector_adversarial_with_kvm_kata_fc() -> None:
    selector = RuntimeSelector(kvm_available=True)
    assert selector.select(WorkloadClass.ADVERSARIAL) == IsolationTier.KATA_FC


def test_selector_adversarial_no_kvm_gvisor_nsjail() -> None:
    selector = RuntimeSelector(kvm_available=False)
    assert selector.select(WorkloadClass.ADVERSARIAL) == IsolationTier.GVISOR_NSJAIL


def test_admission_rejects_untrusted_on_runc() -> None:
    """AC-1: untrusted workload cannot be scheduled on runc."""
    admission = AdmissionController()
    try:
        admission.admit(WorkloadClass.UNTRUSTED, "runc")
    except AdmissionRejected:
        return
    raise AssertionError("untrusted on runc was NOT rejected")


def test_admission_rejects_adversarial_on_runc() -> None:
    admission = AdmissionController()
    try:
        admission.admit(WorkloadClass.ADVERSARIAL, "runc")
    except AdmissionRejected:
        return
    raise AssertionError("adversarial on runc was NOT rejected")


def test_admission_allows_trusted_on_runc() -> None:
    admission = AdmissionController()
    admission.admit(WorkloadClass.TRUSTED, "runc")  # no exception


def test_admission_allows_untrusted_on_runsc() -> None:
    admission = AdmissionController()
    admission.admit(WorkloadClass.UNTRUSTED, "runsc")  # no exception


def test_runtime_class_mapping() -> None:
    assert runtime_class_for(IsolationTier.BASELINE_RUNC) == "runc"
    assert runtime_class_for(IsolationTier.GVISOR_RUNSC) == "runsc"
    assert runtime_class_for(IsolationTier.KATA_FC) == "kata-fc"


def test_seccomp_profile_default_deny() -> None:
    profile = SeccompProfile()
    data = profile.to_dict()
    assert data["defaultAction"] == "SCMP_ACT_ERRNO"
    assert "read" in data["syscalls"][0]["names"]
    # A handful of high-risk syscalls must NOT be in the allowlist.
    for forbidden in ("ptrace", "clone3", "kexec_load", "bpf"):
        assert forbidden not in data["syscalls"][0]["names"]


def test_sandbox_hardening_flags_ac2() -> None:
    """AC-2: baseline hardening flags present on every sandbox."""
    spec = SandboxSpec(
        agent_id="a1",
        image="img",
        tier=IsolationTier.BASELINE_RUNC,
        runtime_class_name="runc",
    )
    flags = spec.hardening_flags
    assert flags["readOnlyRootFilesystem"] is True
    assert flags["allowPrivilegeEscalation"] is False
    assert flags["capabilities_drop"] == ["ALL"]
    assert flags["runAsNonRoot"] is True
    assert flags["runAsUser"] == 65532


def test_docker_runtime_start_constructs_hardened_args(monkeypatch) -> None:
    """Verify the runc backend emits the baseline hardening flags (AC-2)."""
    captured: list[list[str]] = []

    def fake_run(args: list[str]) -> str:
        captured.append(args)
        return "container-123"

    rt = DockerRuntime()
    monkeypatch.setattr(rt, "_run", fake_run)
    spec = SandboxSpec(
        agent_id="a1",
        image="harbor/base",
        tier=IsolationTier.BASELINE_RUNC,
        runtime_class_name="runc",
        env={"K": "V"},
    )
    cid = rt.start(spec)
    assert cid == "container-123"
    run_args = next(a for a in captured if a and a[0] == "run")
    joined = " ".join(run_args)
    assert "--read-only" in joined
    assert "--cap-drop" in joined and "ALL" in joined
    assert "no-new-privileges" in joined
    assert "--user" in joined and "65532:65532" in joined
    assert "agent-a1" in joined


def test_docker_runtime_unavailable(monkeypatch) -> None:
    def boom(args: list[str]) -> str:
        raise RuntimeUnavailable("cannot run docker")

    rt = DockerRuntime()
    monkeypatch.setattr(rt, "_run", boom)
    try:
        rt.status("c1")
    except RuntimeUnavailable:
        return
    raise AssertionError("expected RuntimeUnavailable for missing docker")


def test_admission_rejected_is_a_runtime_error() -> None:
    import pytest

    with pytest.raises(AdmissionRejected):
        AdmissionController().admit(WorkloadClass.UNTRUSTED, "runc")
