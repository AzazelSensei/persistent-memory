import json

import pytest

from persistent_memory import transcripts


def _line(**kw):
    return json.dumps(kw)


def _user_text(cwd, text, ts):
    return _line(
        type="user",
        cwd=cwd,
        timestamp=ts,
        message={"role": "user", "content": text},
    )


def _user_blocks(cwd, text, ts):
    return _line(
        type="user",
        cwd=cwd,
        timestamp=ts,
        message={"role": "user", "content": [{"type": "text", "text": text}]},
    )


def _assistant_text(cwd, text, ts):
    return _line(
        type="assistant",
        cwd=cwd,
        timestamp=ts,
        message={"role": "assistant", "content": [{"type": "text", "text": text}]},
    )


def _assistant_tool(cwd, name, ts, **inp):
    return _line(
        type="assistant",
        cwd=cwd,
        timestamp=ts,
        message={
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "tu1", "name": name, "input": inp}],
        },
    )


def _tool_result(cwd, ts):
    return _line(
        type="user",
        cwd=cwd,
        timestamp=ts,
        message={
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "tu1", "content": "ok"}],
        },
    )


def _meta_line():
    return _line(type="mode", sessionId="x")


def _write_jsonl(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def projects_root(tmp_path):
    root = tmp_path / "projects"

    alpha_cwd = "/Users/dev/Desktop/project-alpha"
    _write_jsonl(
        root / "-Users-dev-Desktop-project-alpha" / "11111111-1111-1111-1111-111111111111.jsonl",
        [
            _meta_line(),
            _user_text(alpha_cwd, "graphify var mi?", "2026-06-01T12:00:00.000Z"),
            _assistant_text(alpha_cwd, "Evet, kontrol ediyorum.", "2026-06-01T12:00:05.000Z"),
            _assistant_tool(alpha_cwd, "Bash", "2026-06-01T12:00:06.000Z", command="ls", description="list"),
            _tool_result(alpha_cwd, "2026-06-01T12:00:07.000Z"),
            "{ this is not valid json",
            _user_blocks(alpha_cwd, "tesekkurler", "2026-06-01T12:00:10.000Z"),
        ],
    )
    _write_jsonl(
        root / "-Users-dev-Desktop-project-alpha" / "22222222-2222-2222-2222-222222222222.jsonl",
        [
            _user_text(alpha_cwd, "ikinci session", "2026-06-02T09:00:00.000Z"),
            _assistant_text(alpha_cwd, "tamam", "2026-06-02T09:00:01.000Z"),
        ],
    )

    webshop_cwd = "/Users/dev/Desktop/webshop"
    _write_jsonl(
        root / "-Users-dev-Desktop-webshop" / "33333333-3333-3333-3333-333333333333.jsonl",
        [
            _user_text(webshop_cwd, "urun sayfasi", "2026-05-20T08:00:00.000Z"),
            _assistant_text(webshop_cwd, "hazirliyorum", "2026-05-20T08:00:02.000Z"),
        ],
    )

    tmp_noise_cwd = "/private/tmp/pm-gtest"
    _write_jsonl(
        root / "-private-tmp-pm-gtest" / "44444444-4444-4444-4444-444444444444.jsonl",
        [_user_text(tmp_noise_cwd, "noise", "2026-06-03T00:00:00.000Z")],
    )

    worktree_cwd = "/Users/dev/Desktop/project-beta/.claude/worktrees/optimistic-joliot"
    _write_jsonl(
        root / "-Users-dev-Desktop-project-beta--claude-worktrees-optimistic-joliot" / "55555555-5555-5555-5555-555555555555.jsonl",
        [_user_text(worktree_cwd, "worktree noise", "2026-06-04T00:00:00.000Z")],
    )

    observer_cwd = "/Users/dev/.claude-mem/observer-sessions"
    _write_jsonl(
        root / "-Users-dev--claude-mem-observer-sessions" / "66666666-6666-6666-6666-666666666666.jsonl",
        [_user_text(observer_cwd, "observer noise", "2026-06-05T00:00:00.000Z")],
    )

    pytest_cwd = "/private/var/folders/x/pytest-of-dev/pytest-99/test_something0/proj"
    _write_jsonl(
        root / "-private-var-folders-pytest-of-dev-pytest-99-test-something0-proj" / "77777777-7777-7777-7777-777777777777.jsonl",
        [_user_text(pytest_cwd, "pytest temp noise", "2026-06-06T00:00:00.000Z")],
    )

    (root / "-empty-dir").mkdir(parents=True, exist_ok=True)

    return root


def test_list_projects_excludes_noise(projects_root):
    projects = transcripts.list_projects(projects_root)
    names = [p.name for p in projects]
    assert "project-alpha" in names
    assert "webshop" in names
    assert "pm-gtest" not in names
    assert all("worktree" not in n.lower() for n in names)
    assert "observer-sessions" not in names
    assert not any("pytest" in n for n in names)
    assert len(projects) == 2


def test_list_projects_derives_name_and_path_from_cwd(projects_root):
    projects = transcripts.list_projects(projects_root)
    alpha = next(p for p in projects if p.name == "project-alpha")
    assert alpha.path == "/Users/dev/Desktop/project-alpha"
    assert alpha.name == "project-alpha"


def test_list_projects_counts_transcripts_and_sessions(projects_root):
    projects = transcripts.list_projects(projects_root)
    alpha = next(p for p in projects if p.name == "project-alpha")
    assert alpha.transcript_count == 2
    assert len(alpha.session_ids) == 2
    assert "11111111-1111-1111-1111-111111111111" in alpha.session_ids


def test_list_projects_ordered_by_last_activity_desc(projects_root):
    projects = transcripts.list_projects(projects_root)
    names = [p.name for p in projects]
    assert names == ["project-alpha", "webshop"]
    alpha = projects[0]
    assert alpha.last_activity == "2026-06-02T09:00:01.000Z"


def test_list_projects_empty_root(tmp_path):
    assert transcripts.list_projects(tmp_path / "nope") == []


def test_list_projects_merges_dirs_with_same_cwd(tmp_path):
    root = tmp_path / "projects"
    cwd = "/Users/dev/Desktop/same"
    _write_jsonl(root / "-Users-dev-Desktop-same" / "a.jsonl",
                 [_user_text(cwd, "a", "2026-06-01T00:00:00.000Z")])
    _write_jsonl(root / "-Users-dev-Desktop-same-dup" / "b.jsonl",
                 [_user_text(cwd, "b", "2026-06-02T00:00:00.000Z")])
    projects = transcripts.list_projects(root)
    same = [p for p in projects if p.path == cwd]
    assert len(same) == 1
    assert same[0].transcript_count == 2


def test_read_transcript_parses_messages(projects_root):
    path = (
        projects_root
        / "-Users-dev-Desktop-project-alpha"
        / "11111111-1111-1111-1111-111111111111.jsonl"
    )
    messages = transcripts.read_transcript(path)
    roles = [m.role for m in messages]
    assert "user" in roles
    assert "assistant" in roles
    user_texts = [m.text for m in messages if m.role == "user" and not m.is_tool]
    assert "graphify var mi?" in user_texts
    assert "tesekkurler" in user_texts
    asst_text = next(m for m in messages if m.role == "assistant" and not m.is_tool)
    assert asst_text.text == "Evet, kontrol ediyorum."
    assert any(m.is_tool for m in messages)


def test_read_transcript_skips_malformed(projects_root):
    path = (
        projects_root
        / "-Users-dev-Desktop-project-alpha"
        / "11111111-1111-1111-1111-111111111111.jsonl"
    )
    messages = transcripts.read_transcript(path)
    assert all(m.text is not None for m in messages)
    assert len(messages) >= 4


def test_read_transcript_missing_file(tmp_path):
    assert transcripts.read_transcript(tmp_path / "nope.jsonl") == []


def test_message_has_timestamp(projects_root):
    path = (
        projects_root
        / "-Users-dev-Desktop-project-alpha"
        / "11111111-1111-1111-1111-111111111111.jsonl"
    )
    messages = transcripts.read_transcript(path)
    first = messages[0]
    assert first.timestamp == "2026-06-01T12:00:00.000Z"


def test_project_transcripts_lists_jsonl(projects_root):
    project_dir = projects_root / "-Users-dev-Desktop-project-alpha"
    paths = transcripts.project_transcripts(project_dir)
    assert len(paths) == 2
    assert all(p.suffix == ".jsonl" for p in paths)


def test_project_transcripts_skips_non_jsonl(projects_root):
    project_dir = projects_root / "-Users-dev-Desktop-project-alpha"
    (project_dir / "notes.txt").write_text("not a transcript", encoding="utf-8")
    paths = transcripts.project_transcripts(project_dir)
    assert all(p.suffix == ".jsonl" for p in paths)
    assert len(paths) == 2
