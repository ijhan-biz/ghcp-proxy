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


def test_repo_from_path():
    f = Attributor._repo_from_path
    assert f("/agents/sessions?page_size=20&repo_nwo=ijhan-biz%2Fghcp-proxy") == "ghcp-proxy"
    assert f("/agents/swe/custom-agents/ijhan-biz/aibuild-squad?exclude=true") == "aibuild-squad"
    assert f("/agents/swe/v1/jobs/ijhan-biz/ghcp-proxy/enabled") == "ghcp-proxy"
    assert f("/agents/sessions/b138a1f4-2896-4c43-9f12-32c2947bc8db") is None
    assert f("/v1/messages") is None
    assert f("") is None


def test_match_repo_to_ws():
    ws = [f"{HOME}/ms/workspace/ghcp-proxy", f"{HOME}/ms/workspace/aibuild-squad"]
    assert Attributor._match_repo_to_ws("ghcp-proxy", ws) == f"{HOME}/ms/workspace/ghcp-proxy"
    assert Attributor._match_repo_to_ws("GHCP-PROXY", ws) == f"{HOME}/ms/workspace/ghcp-proxy"
    assert Attributor._match_repo_to_ws("unknown-repo", ws) is None
    # 중복 basename 은 모호 → None
    dup = [f"{HOME}/a/proj", f"{HOME}/b/proj"]
    assert Attributor._match_repo_to_ws("proj", dup) is None


def test_match_path_to_ws_boundary():
    ws = [f"{HOME}/ms/workspace/foo"]
    # 경계 버그 방지: foo2 는 foo 에 속하지 않음
    assert Attributor._match_path_to_ws(f"{HOME}/ms/workspace/foo2/x.py", ws) is None
    assert Attributor._match_path_to_ws(f"{HOME}/ms/workspace/foo/x.py", ws) == f"{HOME}/ms/workspace/foo"
    # 가장 구체적인(긴) 워크스페이스 우선
    nested = [f"{HOME}/ms/workspace/foo", f"{HOME}/ms/workspace/foo/sub"]
    assert Attributor._match_path_to_ws(f"{HOME}/ms/workspace/foo/sub/x.py", nested) == f"{HOME}/ms/workspace/foo/sub"


def test_workspace_info_folder():
    body = (
        '{"messages":[{"text":"<environment_info>x</environment_info>\\n'
        '<workspace_info>\\nI am working in a workspace with the following folders:\\n'
        f'- {HOME}/ms/workspace/ghcp-proxy \\n</workspace_info>"}}]}}'
    )
    assert Attributor._workspace_info_folder(body) == f"{HOME}/ms/workspace/ghcp-proxy"
    # 폴더 다중 → 모호(None)
    multi = (
        f'<workspace_info>\\n- {HOME}/ms/workspace/a\\n- {HOME}/ms/workspace/b\\n</workspace_info>'
    )
    assert Attributor._workspace_info_folder(multi) is None
    assert Attributor._workspace_info_folder("no info") is None


def test_attribute_multi_narrowed_by_repo_url(monkeypatch):
    a = Attributor(poll=False)
    ws = [f"{HOME}/ms/workspace/ghcp-proxy", f"{HOME}/ms/workspace/aibuild-squad"]
    monkeypatch.setattr(a, "_pid_for_port", lambda sp: (999, "Code Helper"))
    monkeypatch.setattr(a, "_cwd_for_pid", lambda pid: "/")
    monkeypatch.setattr(a, "_vscode_workspaces", lambda: ws)
    res = a.attribute(
        55560, "", "/agents/sessions?page_size=20&repo_nwo=ijhan-biz%2Faibuild-squad"
    )
    assert res["project_dir"] == f"{HOME}/ms/workspace/aibuild-squad"
    assert res["project_source"] == "repo-url"


def test_attribute_multi_narrowed_by_workspace_info(monkeypatch):
    a = Attributor(poll=False)
    ws = [f"{HOME}/ms/workspace/ghcp-proxy", f"{HOME}/ms/workspace/aibuild-squad"]
    monkeypatch.setattr(a, "_pid_for_port", lambda sp: (999, "Code Helper"))
    monkeypatch.setattr(a, "_cwd_for_pid", lambda pid: "/")
    monkeypatch.setattr(a, "_vscode_workspaces", lambda: ws)
    body = f'<workspace_info>\nfolders:\n- {HOME}/ms/workspace/ghcp-proxy \n</workspace_info>'
    res = a.attribute(55561, body, "/v1/messages")
    assert res["project_dir"] == f"{HOME}/ms/workspace/ghcp-proxy"
    assert res["project_source"] == "workspace-info"


def test_attribute_multi_ambiguous_when_no_signal(monkeypatch):
    a = Attributor(poll=False)
    ws = [f"{HOME}/ms/workspace/a", f"{HOME}/ms/workspace/b"]
    monkeypatch.setattr(a, "_pid_for_port", lambda sp: (999, "Code Helper"))
    monkeypatch.setattr(a, "_cwd_for_pid", lambda pid: "/")
    monkeypatch.setattr(a, "_vscode_workspaces", lambda: ws)
    res = a.attribute(55562, "", "/models")
    assert res["project_source"] == "vscode-workspace?"
    assert " | " in res["project_dir"]


def test_attribute_no_port():
    a = Attributor(poll=False)
    res = a.attribute(None, "")
    assert res["client_pid"] is None
    assert res["project_dir"] is None
