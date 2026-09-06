from liki.sandbox import SandboxPolicy, SandboxRunner


POLICY=SandboxPolicy(policy_id="test-isolation-v1",cpu_seconds=1,wall_seconds=3,memory_bytes=64*1024*1024,output_bytes=4096,source_bytes=4096)


def test_generated_code_cannot_read_host_or_credentials(tmp_path,monkeypatch):
    secret=tmp_path/"credential"
    secret.write_text("not-for-research")
    monkeypatch.setenv("LIKI_SECRET","must-not-be-visible")
    source=f"import os\nassert 'LIKI_SECRET' not in os.environ\nassert not os.path.exists({str(secret)!r})\nassert not os.path.exists('/tmp/hoplite/workspace')\nprint('isolated')"
    result=SandboxRunner().run(source,{},POLICY)
    assert result.status=="COMPLETED",result.stderr
    assert result.stdout.strip()=="isolated"


def test_network_and_fork_are_denied():
    source="""import socket, os
for action in (lambda: socket.socket(), os.fork):
    try:
        action()
        raise AssertionError('operation escaped sandbox')
    except PermissionError:
        print('denied')
"""
    result=SandboxRunner().run(source,{},POLICY)
    assert result.exit_code==0,result.stderr
    assert result.stdout.count("denied")==2


def test_runaway_compute_is_bounded():
    result=SandboxRunner().run("while True: pass",{},POLICY)
    assert result.status in {"FAILED_CLOSED","WALL_TIME_LIMIT"}
    assert result.elapsed_seconds<5


def test_policy_writes_and_output_flood_are_bounded():
    result=SandboxRunner().run("open('/usr/policy','w').write('unsafe')",{},POLICY)
    assert result.status=="FAILED_CLOSED"
    flood=SandboxRunner().run("print('x'*100000)",{},POLICY)
    assert len(flood.stdout)<=POLICY.output_bytes
    assert flood.status=="FAILED_CLOSED"
