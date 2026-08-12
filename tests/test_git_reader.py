from __future__ import annotations

from kimi_discord_rpc.git_reader import branch_label, find_git_dir, read_branch


def _make_repo(tmp_path, head_contents: str):
    git_dir = tmp_path / "repo" / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "HEAD").write_text(head_contents, encoding="utf-8")
    return tmp_path / "repo"


def test_reads_branch_name(tmp_path):
    repo = _make_repo(tmp_path, "ref: refs/heads/feat/auth-v2\n")
    info = read_branch(repo)
    assert info is not None
    assert info.name == "feat/auth-v2"
    assert info.detached is False
    assert branch_label(info) == "feat/auth-v2"


def test_finds_repo_from_a_nested_directory(tmp_path):
    repo = _make_repo(tmp_path, "ref: refs/heads/main\n")
    nested = repo / "src" / "deep" / "nested"
    nested.mkdir(parents=True)
    info = read_branch(nested)
    assert info is not None and info.name == "main"


def test_detached_head(tmp_path):
    repo = _make_repo(tmp_path, "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678\n")
    info = read_branch(repo)
    assert info is not None
    assert info.detached is True
    assert info.name == "a1b2c3d"
    assert branch_label(info) == "detached @a1b2c3d"


def test_worktree_git_file(tmp_path):
    real_git = tmp_path / "real" / ".git" / "worktrees" / "wt"
    real_git.mkdir(parents=True)
    (real_git / "HEAD").write_text("ref: refs/heads/wt-branch\n", encoding="utf-8")

    worktree = tmp_path / "checkout"
    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {real_git}\n", encoding="utf-8")

    info = read_branch(worktree)
    assert info is not None and info.name == "wt-branch"


def test_not_a_repo(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert read_branch(plain) is None
    assert branch_label(None) is None


def test_missing_and_empty_inputs(tmp_path):
    assert read_branch(None) is None
    assert read_branch("") is None
    assert read_branch(tmp_path / "does-not-exist") is None


def test_garbage_head_is_rejected(tmp_path):
    repo = _make_repo(tmp_path, "ref: refs/heads/../../etc/passwd\x00\n")
    assert read_branch(repo) is None

    empty = _make_repo(tmp_path / "other", "")
    assert read_branch(empty) is None


def test_find_git_dir_returns_none_outside_repo(tmp_path):
    plain = tmp_path / "nothing"
    plain.mkdir()
    assert find_git_dir(plain) is None
