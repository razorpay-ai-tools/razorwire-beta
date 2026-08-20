"""Re-voice published reels with the CURRENT kokoro settings.

Posts published before `kokoro_voice`/`kokoro_speed` settled carry scene audio that no
longer matches the voice everything else speaks in, and posts published before the
prompt gained the pause and tone rules read breathlessly. This repairs both:

    cd backend && .venv/bin/python scripts/revoice.py --dry-run   # plan only
    cd backend && .venv/bin/python scripts/revoice.py             # re-voice everything
    cd backend && .venv/bin/python scripts/revoice.py --post post_abc123
    cd backend && .venv/bin/python scripts/revoice.py --rescript --post post_abc123

Default mode is FREE: no LLM call, the stored narration text is spoken again through
`render.publish.voice_scenes_to_media` — the same helper the generate path uses, so
repaired audio is encoded and named exactly like freshly published audio.

`--rescript` also regenerates the narration TEXT through the model, which COSTS MONEY
(one call per post). Opt-in only, and it re-fetches the post's original source rather
than inventing one: a post whose source can no longer be read is skipped.

Idempotent: scene audio is keyed on the post id, so a second run overwrites the same
files and rewrites the same URLs. Crash-safe: one commit per post, so a failure halfway
leaves every post before it repaired.

ponytail: does not delete the m4a files the old job-keyed URLs pointed at. They are a
few MB of orphans in .storage and deleting media is not something a repair script should
do on its own.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session, col, select  # noqa: E402

from app.aidocs import AidocsUnavailable, fetch_doc  # noqa: E402
from app.config import settings  # noqa: E402
from app.models import Post, _engine, init_db  # noqa: E402
from app.pipeline import run_script_stage, storyboard_to_json  # noqa: E402
from app.slack import SlackUnavailable, fetch_thread  # noqa: E402
from app.storyboard import Storyboard  # noqa: E402


def scene_count(post: Post) -> int:
    return len((post.storyboard or {}).get("scenes") or [])


def skip_reason(post: Post) -> str | None:
    """Why this post cannot be re-voiced, or None when it can."""
    if not scene_count(post):
        return "no storyboard scenes"
    if post.media_url:
        # The MP4 has the old voice baked into its audio track. Re-voicing only the
        # storyboard would leave the reel view and the file saying the same words at
        # different times, which is worse than a stale voice in both.
        return "MP4-backed (baked-in audio track would desync)"
    return None


def refetch_source(sb: Storyboard) -> tuple[dict, str] | None:
    """The kwargs `run_script_stage` needs to regenerate this post, or None.

    Returns ``(kwargs, description)``. None means the source is gone or was never
    stored, and the caller must skip rather than make one up.
    """
    kind = sb.source.kind
    if kind == "aidoc":
        if not sb.source.doc_id:
            return None
        doc = fetch_doc(sb.source.doc_id)
        return (
            {
                "kind": "aidoc",
                "text": doc.to_prompt_text(),
                "doc_id": doc.doc_id,
                "doc_title": doc.title,
                "doc_url": doc.url,
            },
            f"aidoc {doc.doc_id}",
        )
    if kind == "slack":
        if not sb.source.url:
            return None
        thread = fetch_thread(sb.source.url)
        return (
            {
                "kind": "slack",
                "text": thread.to_prompt_text(),
                "doc_title": thread.title,
                "doc_url": thread.url,
            },
            f"slack thread {thread.url}",
        )
    return None  # kind == "topic": the prompt was never stored on the post


def rescript(sb: Storyboard) -> Storyboard | None:
    """Regenerate this post's storyboard from its original source. One LLM call.

    Keeps the existing title: it is what the feed and any shared link show, and a
    multi-part post's "— Part 2/3" suffix only exists on the stored one.
    """
    try:
        resolved = refetch_source(sb)
    except (AidocsUnavailable, SlackUnavailable) as exc:
        print(f"  ! source unreadable ({exc}); keeping the existing narration")
        return None
    if resolved is None:
        print(f"  ! no re-fetchable source (kind={sb.source.kind}); keeping the existing narration")
        return None

    kwargs, described = resolved
    print(f"  re-scripting from {described}")
    fresh = run_script_stage(**kwargs)
    fresh.meta.title = sb.meta.title
    return fresh


def revoice(session: Session, post: Post, *, with_rescript: bool) -> tuple[int, int]:
    """Repair one post in place and commit. Returns ``(scenes, total_ms)``."""
    from app.render.publish import voice_scenes_to_media

    sb = Storyboard.model_validate(post.storyboard)
    if with_rescript:
        sb = rescript(sb) or sb

    # Stamps a fresh audioUrl and a freshly measured durationMs on every scene, so the
    # stale pair is replaced rather than merged with.
    work_dir = Path(settings.work_dir) / f"revoice_{post.id}"
    if not voice_scenes_to_media(sb, work_dir, post.id):
        raise RuntimeError("no audio produced (ffmpeg or a TTS voice is missing)")

    post.storyboard = storyboard_to_json(sb)
    session.add(post)
    session.commit()
    return len(sb.scenes), sum(scene.duration_ms or 0 for scene in sb.scenes)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--post", metavar="ID", help="repair one post instead of all of them")
    parser.add_argument("--dry-run", action="store_true", help="report the plan, change nothing")
    parser.add_argument(
        "--rescript",
        action="store_true",
        help="also regenerate the narration text via the LLM. COSTS MONEY: one call per post.",
    )
    args = parser.parse_args()

    init_db()
    with Session(_engine) as session:
        query = select(Post).order_by(col(Post.created_at))
        if args.post:
            query = query.where(Post.id == args.post)
        posts = list(session.exec(query).all())
    if args.post and not posts:
        sys.exit(f"no post {args.post}")

    eligible = [p for p in posts if skip_reason(p) is None]
    skipped = [(p, skip_reason(p)) for p in posts if skip_reason(p) is not None]
    scenes = sum(scene_count(p) for p in eligible)

    print(f"{len(posts)} post(s) considered: {len(eligible)} to re-voice, {len(skipped)} skipped")
    for post, reason in skipped:
        print(f"  skip {post.id}  {reason}  ({post.title[:44]})")
    for post in eligible:
        print(f"  plan {post.id}  {scene_count(post)} scene(s)  ({post.title[:44]})")
    print(
        f"voice: {settings.kokoro_voice} at speed {settings.kokoro_speed} "
        f"(backend {settings.render_tts}) -> {scenes} scene(s) of audio"
    )

    if args.rescript:
        # Printed before anything happens, in both modes, because the number of paid
        # calls is the one thing worth knowing before saying yes to this flag.
        print(
            f"\n!! --rescript WILL SPEND MONEY: {len(eligible)} LLM call(s) to "
            f"{settings.llm_model}, one per post, before any audio is made."
        )

    if args.dry_run:
        print("\ndry run: nothing changed")
        return

    done = failed = 0
    for index, post in enumerate(eligible, start=1):
        print(f"\n[{index}/{len(eligible)}] {post.id} {post.title[:50]}")
        with Session(_engine) as session:
            fresh = session.get(Post, post.id)
            try:
                count, total_ms = revoice(session, fresh, with_rescript=args.rescript)
                print(f"  ok {count} scene(s), {total_ms / 1000:.1f}s of narration")
                done += 1
            except Exception as exc:  # one bad post must not strand the rest
                session.rollback()
                print(f"  FAILED {type(exc).__name__}: {exc}")
                failed += 1

    print(f"\nre-voiced {done} post(s), {failed} failed, {len(skipped)} skipped")


if __name__ == "__main__":
    main()
