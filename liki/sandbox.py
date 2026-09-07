from __future__ import annotations

import ctypes
import ctypes.util
import errno
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from pydantic import Field

from liki.core import Contract, DomainError, content_hash


class SandboxPolicy(Contract):
    policy_id: str
    cpu_seconds: int = Field(ge=1,le=300)
    wall_seconds: int = Field(ge=1,le=600)
    memory_bytes: int = Field(ge=32*1024*1024,le=4*1024*1024*1024)
    output_bytes: int = Field(ge=1,le=10*1024*1024)
    source_bytes: int = Field(ge=1,le=1024*1024)


class SandboxResult(Contract):
    status: str
    exit_code: int | None
    stdout: str
    stderr: str
    elapsed_seconds: float
    source_hash: str
    input_hash: str
    policy_id: str


def _seccomp_filter() -> int:
    library=ctypes.util.find_library("seccomp")
    if not library:
        raise DomainError("SANDBOX_UNAVAILABLE","libseccomp is required")
    lib=ctypes.CDLL(library)
    lib.seccomp_init.argtypes=[ctypes.c_uint32]
    lib.seccomp_init.restype=ctypes.c_void_p
    lib.seccomp_syscall_resolve_name.argtypes=[ctypes.c_char_p]
    lib.seccomp_syscall_resolve_name.restype=ctypes.c_int
    lib.seccomp_rule_add.argtypes=[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_int,ctypes.c_uint]
    lib.seccomp_export_bpf.argtypes=[ctypes.c_void_p,ctypes.c_int]
    lib.seccomp_release.argtypes=[ctypes.c_void_p]
    context=lib.seccomp_init(0x7FFF0000)
    if not context:
        raise DomainError("SANDBOX_UNAVAILABLE")
    fd=os.memfd_create("liki-sandbox-policy",os.MFD_CLOEXEC)
    try:
        # Network namespaces are unavailable on some hosts; syscall denial is mandatory on all.
        for name in ("socket","socketpair","connect","bind","listen","accept","accept4",
                     "ptrace","process_vm_readv","process_vm_writev","mount","umount2","pivot_root",
                     "setns","unshare","clone","clone3","fork","vfork","bpf","perf_event_open",
                     "keyctl","add_key","request_key","open_by_handle_at","userfaultfd","io_uring_setup"):
            number=lib.seccomp_syscall_resolve_name(name.encode())
            if number>=0 and lib.seccomp_rule_add(context,0x00050000|errno.EPERM,number,0)<0:
                raise DomainError("SANDBOX_POLICY_INSTALL_FAILED")
        if lib.seccomp_export_bpf(context,fd)<0:
            raise DomainError("SANDBOX_POLICY_INSTALL_FAILED")
        os.lseek(fd,0,os.SEEK_SET)
        return fd
    except BaseException:
        os.close(fd)
        raise
    finally:
        lib.seccomp_release(context)


class SandboxRunner:
    def run(self,source:str,inputs:dict,policy:SandboxPolicy)->SandboxResult:
        if len(source.encode())>policy.source_bytes:
            raise DomainError("SOURCE_LIMIT_EXCEEDED")
        if not Path("/usr/bin/bwrap").exists():
            raise DomainError("SANDBOX_UNAVAILABLE")
        input_bytes=json.dumps(inputs,allow_nan=False).encode()
        if len(input_bytes)>policy.output_bytes:
            raise DomainError("INPUT_LIMIT_EXCEEDED")
        started=time.monotonic()
        with tempfile.TemporaryDirectory(prefix="liki-experiment-") as directory:
            root=Path(directory)
            (root/"candidate.py").write_text(source)
            (root/"input.json").write_bytes(input_bytes)
            (root/"work").mkdir()
            seccomp=_seccomp_filter()
            command=["/usr/bin/prlimit",f"--cpu={policy.cpu_seconds}",f"--as={policy.memory_bytes}",f"--fsize={policy.output_bytes}","--nofile=32","--core=0","--",
                     "/usr/bin/bwrap","--unshare-user","--unshare-pid","--unshare-ipc","--unshare-uts",
                     "--die-with-parent","--new-session","--cap-drop","ALL","--clearenv",
                     "--ro-bind","/usr","/usr","--ro-bind","/lib","/lib","--symlink","usr/lib64","/lib64",
                     "--proc","/proc","--dev","/dev","--ro-bind",str(root/"candidate.py"),"/candidate.py",
                     "--ro-bind",str(root/"input.json"),"/input.json","--bind",str(root/"work"),"/work",
                     "--chdir","/work","--setenv","PATH","/usr/bin","--setenv","LANG","C.UTF-8",
                     "--seccomp",str(seccomp),"/usr/bin/python3","-I","-B","/candidate.py"]
            try:
                with (root/"stdout").open("wb") as out,(root/"stderr").open("wb") as err:
                    process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=out,stderr=err,
                        env={"PATH":"/usr/bin:/bin"},pass_fds=(seccomp,),start_new_session=True)
                    status="COMPLETED"
                    try:
                        code=process.wait(timeout=policy.wall_seconds)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                        code=None
                        status="WALL_TIME_LIMIT"
                    if code is not None and code!=0:
                        status="FAILED_CLOSED"
                stdout=(root/"stdout").read_bytes()[:policy.output_bytes].decode(errors="replace")
                stderr=(root/"stderr").read_bytes()[:policy.output_bytes].decode(errors="replace")
                return SandboxResult(status=status,exit_code=code,stdout=stdout,stderr=stderr,
                    elapsed_seconds=time.monotonic()-started,source_hash=content_hash(source),input_hash=content_hash(inputs),policy_id=policy.policy_id)
            finally:
                os.close(seccomp)
