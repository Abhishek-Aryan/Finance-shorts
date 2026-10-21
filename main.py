"""Finance Shorts - main CLI entry point"""
from __future__ import annotations

import argparse
import sys
import logging
import io

# Force UTF-8 output on Windows to avoid cp1252 UnicodeEncodeError
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import logger_setup
import config
from storage import database, spreadsheet_manager

logger = logging.getLogger(__name__)


def cmd_init(args: argparse.Namespace) -> None:
    """Initialise database, create Excel queue, copy .env template."""
    logger_setup.setup_logging("INFO")
    logger.info("=== Finance Shorts — init ===")

    # 1. Validate config
    warnings = config.validate()
    for w in warnings:
        logger.warning("Config warning: %s", w)

    # 2. Initialise SQLite
    database.init_db()
    logger.info("[OK] Database ready: %s", config.SQLITE_DB)

    # 3. Create / refresh Excel workbook
    spreadsheet_manager.create_workbook()
    logger.info("[OK] Excel queue ready: %s", config.EXCEL_FILE)

    # 4. Sync Excel topics → SQLite
    topics = spreadsheet_manager.read_topics()
    synced = 0
    for t in topics:
        if t.get("topic_id") and t.get("topic"):
            database.upsert_topic(
                topic_id             = str(t["topic_id"]),
                topic                = str(t["topic"]),
                category             = str(t.get("category", "")),
                difficulty_level     = int(t.get("difficulty_level") or 1),
                audience             = str(t.get("audience", "beginners")),
                key_learning_objective = str(t.get("key_learning_objective", "")),
                prerequisites        = str(t.get("prerequisites", "")),
            )
            synced += 1
    logger.info("[OK] Synced %d topics from Excel -> SQLite", synced)

    # 5. Create .env if not present
    env_path = config.ROOT_DIR / ".env"
    example_path = config.ROOT_DIR / ".env.example"
    if not env_path.exists() and example_path.exists():
        import shutil
        shutil.copy(example_path, env_path)
        logger.info("[OK] Created .env from .env.example -- please review and fill in your credentials")
    else:
        logger.info("  .env already exists, skipping")

    print("\nProject initialised successfully!")
    print(f"   Database : {config.SQLITE_DB}")
    print(f"   Excel    : {config.EXCEL_FILE}")
    print(f"   Mode     : {config.PUBLISHING_MODE}")
    if warnings:
        print(f"\n[WARN] {len(warnings)} config warning(s) -- review above output")


def cmd_topics(args: argparse.Namespace) -> None:
    """List all topics with their current status."""
    logger_setup.setup_logging("WARNING")
    topics = database.list_topics(status=getattr(args, "status", None))
    if not topics:
        print("No topics found. Run: python main.py init")
        return
    print(f"\n{'ID':<10} {'Status':<20} {'Lvl':<4} {'Topic'}")
    print("-" * 80)
    for t in topics:
        print(f"{t['topic_id']:<10} {t['status']:<20} {t['difficulty_level']:<4} {t['topic'][:55]}")
    print(f"\nTotal: {len(topics)}")


def cmd_status(args: argparse.Namespace) -> None:
    """Show a pipeline status summary."""
    logger_setup.setup_logging("WARNING")
    from storage.database import get_connection
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM topics GROUP BY status ORDER BY cnt DESC"
        ).fetchall()

    print("\n=== Finance Shorts — Pipeline Status ===\n")
    for r in rows:
        bar = "█" * min(r["cnt"], 40)
        print(f"  {r['status']:<22} {r['cnt']:>4}  {bar}")
    print()

    next_t = database.get_next_eligible_topic()
    if next_t:
        print(f"  Next eligible: [{next_t['topic_id']}] {next_t['topic'][:55]}")
    else:
        print("  No eligible topics in queue")
    print()


def cmd_generate(args: argparse.Namespace) -> None:
    """Generate a script for a topic using the local Ollama LLM."""
    logger_setup.setup_logging("INFO")
    topic_id = getattr(args, "topic_id", None)
    auto_approve = getattr(args, "auto_approve", False)

    print(f"\nGenerating script for: {topic_id or 'next eligible topic'}")
    print("This may take 30-120 seconds depending on your GPU...\n")

    try:
        from content.pipeline import run_generate
        result = run_generate(topic_id=topic_id, auto_approve=auto_approve)
    except RuntimeError as e:
        print(f"\n[ERROR] {e}")
        print("Make sure Ollama is running: ollama serve")
        print(f"And the model is pulled: ollama pull {config.OLLAMA_MODEL}")
        return

    script = result["script"]
    status = result["status"]

    print(f"Status   : {status}")
    print(f"Topic ID : {result['topic_id']}")
    print(f"Title    : {script.get('video_title', 'N/A')}")
    print(f"Words    : {script.get('estimated_word_count', '?')}")
    print(f"Scenes   : {len(script.get('scene_plan', []))}")

    if result["errors"]:
        print("\nErrors:")
        for e in result["errors"]:
            print(f"  [FAIL] {e}")

    if result["warnings"]:
        print("\nWarnings:")
        for w in result["warnings"]:
            print(f"  [WARN] {w}")

    print("\nScript preview (first 300 chars):")
    print("-" * 60)
    print(script.get("full_script", "")[:300] + "...")
    print("-" * 60)
    print(f"\nScript saved to database. Status: {status}")
    if status == "NEEDS_REVIEW":
        print("Run 'python main.py approve --topic-id <id>' after reviewing.")


def cmd_produce(args: argparse.Namespace) -> None:
    """Produce video for a topic (audio + visuals + ffmpeg)."""
    logger_setup.setup_logging("INFO")
    topic_id = getattr(args, "topic_id", None)
    if not topic_id:
        with database.get_connection() as conn:
            row = conn.execute(
                "SELECT topic_id FROM topics WHERE status IN ('SCRIPT_GENERATED', 'SCRIPT_APPROVED') "
                "ORDER BY difficulty_level, topic_id LIMIT 1"
            ).fetchone()
            if row:
                topic_id = row["topic_id"]
            else:
                print("No topic with generated script found. Run 'generate' on a topic first.")
                return

    print(f"\nProducing video for topic: {topic_id}...")
    from production.video_pipeline import produce_video_for_topic
    res = produce_video_for_topic(topic_id)
    print("\nVideo production complete!")
    print(f"  Topic ID : {res['topic_id']}")
    print(f"  Video    : {res['video_path']}")
    print(f"  Duration : {res['duration']:.1f}s")
    print(f"  Size     : {res['size_mb']} MB")
    print(f"  Status   : {res['status']}")


def cmd_publish(args: argparse.Namespace) -> None:
    """Publish a ready video to YouTube and Instagram."""
    logger_setup.setup_logging("INFO")
    topic_id = getattr(args, "topic_id", None)
    if not topic_id:
        ready = database.list_topics(status=database.Status.VIDEO_READY)
        if ready:
            topic_id = ready[0]["topic_id"]
        else:
            print("No VIDEO_READY topics found to publish.")
            return

    print(f"\nPublishing topic: {topic_id} (Mode: {config.PUBLISHING_MODE.upper()})...")
    from publishing.youtube_publisher import publish_to_youtube
    from publishing.instagram_publisher import publish_to_instagram
    from storage.spreadsheet_manager import sync_db_to_excel

    yt = publish_to_youtube(topic_id)
    ig = publish_to_instagram(topic_id)
    sync_db_to_excel()

    print("\nPublished successfully!")
    print(f"  YouTube URL   : {yt.get('published_url')}")
    print(f"  Instagram URL : {ig.get('published_url')}")
    print("  Excel updated : Yes")


def cmd_run_daily(args: argparse.Namespace) -> None:
    """Run the complete autonomous daily cycle."""
    logger_setup.setup_logging("INFO")
    print("\n=== STARTING AUTONOMOUS DAILY WORKER ===")
    from automation.daily_worker import run_daily_cycle
    max_vids = getattr(args, "max_videos", 1) or 1
    report = run_daily_cycle(max_videos_to_publish=int(max_vids))
    print("\n=== DAILY CYCLE SUMMARY ===")
    print(f"  Produced  : {len(report['produced_videos'])} video(s)")
    print(f"  Published : {len(report['published_videos'])} video(s)")
    print(f"  Errors    : {len(report['errors'])}")
    for p in report["published_videos"]:
        print(f"    - [{p['topic_id']}] {p['youtube'].get('published_url')}")


def cmd_auth_youtube(args: argparse.Namespace) -> None:
    """Run interactive YouTube OAuth2 authentication flow."""
    from setup_youtube_oauth import authenticate_youtube
    force = getattr(args, "force", False)
    authenticate_youtube(force_reauth=force)


def cmd_sync(args: argparse.Namespace) -> None:
    """Sync SQLite state to Excel queue spreadsheet."""
    logger_setup.setup_logging("INFO")
    from storage.spreadsheet_manager import sync_db_to_excel
    sync_db_to_excel()
    print("[OK] SQLite state synced to Excel workbook successfully.")


def cmd_schedule_status(args: argparse.Namespace) -> None:
    from automation.schedule_runner import print_schedule_status
    print_schedule_status()


def cmd_publish_next(args: argparse.Namespace) -> None:
    logger_setup.setup_logging("INFO")
    from automation.schedule_runner import publish_next_topic
    code = publish_next_topic(dry_run=args.dry_run)
    sys.exit(code)


def cmd_run_schedule(args: argparse.Namespace) -> None:
    logger_setup.setup_logging("INFO")
    from automation.schedule_runner import run_trigger_daemon
    run_trigger_daemon(dry_run=args.dry_run)


def cmd_install_scheduler(args: argparse.Namespace) -> None:
    import subprocess
    script = config.ROOT_DIR / "tools" / "setup_scheduler.ps1"
    subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-File", str(script)])


def cmd_uninstall_scheduler(args: argparse.Namespace) -> None:
    import subprocess
    script = config.ROOT_DIR / "tools" / "uninstall_scheduler.ps1"
    subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-File", str(script)])


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="finance-shorts",
        description="Automated Finance YouTube Shorts pipeline",
    )
    sub = p.add_subparsers(dest="command")

    sub.add_parser("init",   help="Initialise database and Excel queue")
    sub.add_parser("status", help="Show pipeline status summary")
    sub.add_parser("sync",   help="Sync SQLite state to Excel queue")

    # 14-Day Schedule commands
    sub.add_parser("schedule-status", help="Display 14-day publishing schedule status")

    pn = sub.add_parser("publish-next", help="Produce and publish the next pending topic immediately")
    pn.add_argument("--dry-run", action="store_true", help="Generate without real video rendering/publishing")

    rs = sub.add_parser("run-schedule", help="Run background daemon triggering at 9AM, 3PM, 8PM IST")
    rs.add_argument("--dry-run", action="store_true", help="Simulate without real video rendering/publishing")

    ay = sub.add_parser("auth-youtube", help="Authenticate YouTube Channel via OAuth2")
    ay.add_argument("--force", action="store_true", help="Force re-authentication even if token exists")

    t = sub.add_parser("topics", help="List topics")
    t.add_argument("--status", help="Filter by status (e.g. IDEA, VIDEO_READY, PUBLISHED)")

    g = sub.add_parser("generate", help="Generate script for a topic via local LLM")
    g.add_argument("--topic-id", dest="topic_id", help="Specific topic ID (default: next eligible)")
    g.add_argument("--auto-approve", dest="auto_approve", action="store_true",
                   help="Skip manual review even for unverified claims")

    prod = sub.add_parser("produce", help="Render video (audio + visuals + FFmpeg)")
    prod.add_argument("--topic-id", dest="topic_id", help="Topic ID to render")

    pub = sub.add_parser("publish", help="Publish video to YouTube & Instagram")
    pub.add_argument("--topic-id", dest="topic_id", help="Topic ID to publish")

    rd = sub.add_parser("run-daily", help="Run full autonomous daily production & publish cycle")
    rd.add_argument("--max-videos", dest="max_videos", type=int, default=1,
                    help="Max videos to publish in this cycle (default: 1)")

    # Scheduler setup
    sub.add_parser("install-scheduler", help="Register Windows Task Scheduler jobs (9AM, 3PM, 8PM IST)")
    sub.add_parser("uninstall-scheduler", help="Remove Windows Task Scheduler jobs")

    return p


def main() -> None:
    parser = _build_parser()
    args   = parser.parse_args()

    dispatch = {
        "init":                cmd_init,
        "topics":              cmd_topics,
        "status":              cmd_status,
        "schedule-status":     cmd_schedule_status,
        "publish-next":        cmd_publish_next,
        "run-schedule":        cmd_run_schedule,
        "install-scheduler":   cmd_install_scheduler,
        "uninstall-scheduler": cmd_uninstall_scheduler,
        "generate":            cmd_generate,
        "produce":             cmd_produce,
        "publish":             cmd_publish,
        "run-daily":           cmd_run_daily,
        "sync":                cmd_sync,
        "auth-youtube":        cmd_auth_youtube,
    }

    if args.command in dispatch:
        dispatch[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

