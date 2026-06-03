"""attribution 단위 테스트 (lsof 호출은 모킹)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from ghcp_proxy import attribution
from ghcp_proxy.attribution import Attributor, is_project_dir

HOME = os.path.expanduser("~")


def test_is_project_dir():
    assert is_project_dir(f"{HOME}/ms/workspace/proj") is True
    assert is_project_dir("/") is False
    assert is_project_dir(f"{HOME}") is False  # 깊이 부족
    assert is_project_dir(f"{HOME}/Library/Caches/x") is False
    assert is_project_dir("/usr/local/bin") is False


def test_path_from_body():
    body = f'{{"messages":[{{"content":"see file://{HOME}/ms/workspace/proj/main.py here"}}]}}'
    assert Attributor._path_from_body(body) == f"{HOME}/ms/workspace/proj/main.py"
    assert Attributor._path_from_body("no path here") is None


def test_attribute_cwd_path(monkeypatch):
    a = Attributor(poll=False)
    monkeypatch.setattr(a, "_pid_for_port", lambda sp: (12345, "copilot"))
    monkeypatch.setattr(a, "_cwd_for_pid", lambda pid: f"{HOME}/ms/workspace/myproj")
    res = a.attribute(55555, "")
    assert res["client_pid"] == 12345
    assert res["client_process"] == "copilot"
    assert res["project_dir"] == f"{HOME}/ms/workspace/myproj"
    assert res["project_source"] == "cwd"


def test_attribute_vscode_single_workspace(monkeypatch):
    a = Attributor(poll=False)
    monkeypatch.setattr(a, "_pid_for_port", lambda sp: (999, "Code Helper"))
    monkeypatch.setattr(a, "_cwd_for_pid", lambda pid: "/")  # 공유 헬퍼
    monkeypatch.setattr(a, "_vscode_workspaces", lambda: [f"{HOME}/ms/workspace/only"])
    res = a.attribute(55556, "")
    assert res["project_dir"] == f"{HOME}/ms/workspace/only"
    assert res["project_source"] == "vscode-workspace"


def test_attribute_vscode_multi_narrowed_by_body(monkeypatch):
    a = Attributor(poll=False)
    ws = [f"{HOME}/ms/workspace/a", f"{HOME}/ms/workspace/b"]
    monkeypatch.setattr(a, "_pid_for_port", lambda sp: (999, "Code Helper"))
    monkeypatch.setattr(a, "_cwd_for_pid", lambda pid: "/")
    monkeypatch.setattr(a, "_vscode_workspaces", lambda: ws)
    body = f'{{"path":"{HOME}/ms/workspace/b/src/x.py"}}'
    res = a.attribute(55557, body)
    assert res["project_dir"] == f"{HOME}/ms/workspace/b"
    assert res["project_source"] == "body-path"


def test_attribute_no_port():
    a = Attributor(poll=False)
    res = a.attribute(None, "")
    assert res["client_pid"] is None
    assert res["project_dir"] is None
