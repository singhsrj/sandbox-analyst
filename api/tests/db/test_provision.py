from pathlib import Path

from db.provision import build_url, set_env_values

ADMIN = "postgresql://neondb_owner:secret@ep-cool-name-123.c-2.ap-southeast-1.aws.neon.tech/neondb?sslmode=require"


def test_build_url_pooled_and_direct() -> None:
    pooled = build_url(ADMIN, "analyst_ro", "p@ss/word", pooled=True)
    direct = build_url(ADMIN, "app_rw", "pw", pooled=False)
    assert "@ep-cool-name-123-pooler.c-2.ap-southeast-1.aws.neon.tech/neondb" in pooled
    assert pooled.startswith("postgresql://analyst_ro:p%40ss%2Fword@")
    assert "-pooler" not in direct
    assert pooled.endswith("?sslmode=require")


def test_build_url_from_pooled_admin_url_still_gives_direct() -> None:
    pooled_admin = ADMIN.replace("ep-cool-name-123", "ep-cool-name-123-pooler")
    assert "-pooler" not in build_url(pooled_admin, "app_rw", "pw", pooled=False)
    assert build_url(pooled_admin, "x", "y", pooled=True).count("-pooler") == 1


def test_set_env_values_keeps_comments_and_other_lines(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("A=1\nDB_URL=old    # (secret) keep me\nB=2\n", encoding="utf-8")
    set_env_values(env, {"DB_URL": "new", "NEW_KEY": "v"})
    lines = env.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "A=1"
    assert lines[1] == "DB_URL=new    # (secret) keep me"
    assert lines[2] == "B=2"
    assert lines[-1] == "NEW_KEY=v"
