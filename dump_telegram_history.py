# dump_telegram_history.py
import os, json, argparse, asyncio
from datetime import datetime
from pathlib import Path
from tqdm.asyncio import tqdm
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from dotenv import load_dotenv

def to_serializable(msg):
    def serialize_reactions(r):
        if not r:
            return None
        # total count from aggregated results if available
        try:
            total = sum(getattr(x, "count", 0) for x in (r.results or []))
        except Exception:
            total = None
        # recent reaction emojis/custom ids
        recent = []
        for rr in (getattr(r, "recent_reactions", None) or []):
            try:
                rx = rr.reaction
                emo = getattr(rx, "emoticon", None)
                if emo:
                    recent.append(emo)
                else:
                    doc_id = getattr(rx, "document_id", None)
                    recent.append(f"custom:{doc_id}" if doc_id else str(rx))
            except Exception:
                recent.append(None)
        return {"total": total, "recent": recent}

    s = msg.sender
    return {
        "id": msg.id,
        "date": msg.date.isoformat() if getattr(msg, "date", None) else None,
        "chat_id": getattr(msg, "chat_id", None),
        "sender_id": getattr(msg, "sender_id", None),
        "sender_username": getattr(s, "username", None) if s else None,
        "sender_first_name": getattr(s, "first_name", None) if s else None,
        "sender_last_name": getattr(s, "last_name", None) if s else None,
        "message": getattr(msg, "message", None),
        "reply_to_msg_id": getattr(msg, "reply_to_msg_id", None),
        "views": getattr(msg, "views", None),
        "forwards": getattr(msg, "forwards", None),
        "reactions": serialize_reactions(getattr(msg, "reactions", None)),
        "media": bool(getattr(msg, "media", None)),
    }

async def main():
    ap = argparse.ArgumentParser(description="Export Telegram group history")
    ap.add_argument("--chat", required=True, help="@username, invite link, or numeric ID")
    ap.add_argument("--json", default="messages.jsonl", help="Output JSONL path")
    ap.add_argument("--media-dir", default=None, help="Download media to this folder")
    ap.add_argument("--reverse", action="store_true", help="Write oldest→newest")
    ap.add_argument("--limit", type=int, default=None, help="Max messages (debug)")
    ap.add_argument("--as-bot-token", default=None, help="Optional: login as bot (history limits apply)")
    ap.add_argument("--batch-size", type=int, default=None, help="Write JSON batches of this size to *_partNNNNN.json files")

    # Rate limiting / backoff
    ap.add_argument("--sleep-per-msg", type=float, default=0.0, help="Seconds to sleep after each message processed")
    ap.add_argument("--sleep-every", type=int, default=0, help="Sleep every N messages (0 to disable)")
    ap.add_argument("--sleep-seconds", type=float, default=0.0, help="Seconds to sleep when --sleep-every triggers")
    ap.add_argument("--max-retries", type=int, default=3, help="Max retries on transient errors (media download)")
    ap.add_argument("--retry-backoff", type=float, default=1.5, help="Initial backoff seconds; doubles each retry")
    ap.add_argument("--flood-threshold", type=int, default=300, help="Auto-sleep FloodWaits under this many seconds")

    args = ap.parse_args()

    load_dotenv()  # from .env file if present

    api_id = int(os.getenv("API_ID"))
    api_hash = os.getenv("API_HASH")
    session = os.environ.get("TG_SESSION", "tg_history")

    # Client with retry + flood sleep configuration
    client = TelegramClient(
        session,
        api_id,
        api_hash,
        request_retries=max(0, args.max_retries),
        retry_delay=max(0.0, args.retry_backoff),
        flood_sleep_threshold=max(0, args.flood_threshold),
        connection_retries=3,
    )
    if args.as_bot_token:
        await client.start(bot_token=args.as_bot_token)
    else:
        await client.start()  # interactive login on first run

    entity = await client.get_entity(args.chat)

    # Prepare outputs
    out_path = Path(args.json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    media_dir = Path(args.media_dir) if args.media_dir else None
    if media_dir:
        media_dir.mkdir(parents=True, exist_ok=True)

    # Count for progress bar
    try:
        total = (await client.get_messages(entity, limit=0)).total
    except Exception:
        total = None  # unknown; tqdm will run without a fixed total
    if args.limit is not None:
        if total is not None:
            total = min(total, args.limit)
        else:
            total = args.limit

    # Iterate
    it = client.iter_messages(
        entity,
        reverse=args.reverse,   # True: oldest→newest
        limit=args.limit,
    )

    written = 0
    batching = isinstance(args.batch_size, int) and args.batch_size > 0
    batch = []
    batch_idx = 1

    def write_batch(records, idx):
        base_name = out_path.stem
        file_name = f"{base_name}_part{idx:05d}.json"
        batch_path = out_path.parent / file_name
        with batch_path.open("w", encoding="utf-8") as bf:
            json.dump(records, bf, ensure_ascii=False)
        return batch_path

    async def maybe_rate_sleep():
        if args.sleep_per_msg and args.sleep_per_msg > 0:
            await asyncio.sleep(args.sleep_per_msg)
        if args.sleep_every and args.sleep_every > 0 and args.sleep_seconds and args.sleep_seconds > 0:
            if written > 0 and (written % args.sleep_every) == 0:
                await asyncio.sleep(args.sleep_seconds)

    async def download_with_retry(msg):
        if not media_dir:
            return None, None
        attempt = 0
        backoff = max(0.0, args.retry_backoff)
        while True:
            try:
                fn = await msg.download_media(media_dir)
                return str(fn), None
            except FloodWaitError as e:
                await asyncio.sleep(e.seconds + 1)
                # no attempt increment; FloodWait is not a failure
            except Exception as e:
                attempt += 1
                if attempt > max(0, args.max_retries):
                    return None, repr(e)
                await asyncio.sleep(backoff)
                backoff = backoff * 2 if backoff > 0 else 0

    pbar = tqdm(total=total, desc="Exporting", unit="msg")
    if not batching:
        with out_path.open("w", encoding="utf-8") as f:
            async for msg in it:
                try:
                    rec = to_serializable(msg)
                    if media_dir and getattr(msg, "media", None):
                        fn, err = await download_with_retry(msg)
                        if fn:
                            rec["media_path"] = fn
                        if err:
                            rec["media_error"] = err
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                except Exception as e:
                    f.write(json.dumps({"id": getattr(msg, "id", None), "error": repr(e)}) + "\n")
                written += 1
                pbar.update(1)
                await maybe_rate_sleep()
    else:
        async for msg in it:
            try:
                rec = to_serializable(msg)
                if media_dir and getattr(msg, "media", None):
                    fn, err = await download_with_retry(msg)
                    if fn:
                        rec["media_path"] = fn
                    if err:
                        rec["media_error"] = err
                batch.append(rec)
            except Exception as e:
                batch.append({"id": getattr(msg, "id", None), "error": repr(e)})
            written += 1
            if len(batch) >= args.batch_size:
                write_batch(batch, batch_idx)
                batch_idx += 1
                batch = []
            pbar.update(1)
            await maybe_rate_sleep()
        if batch:
            write_batch(batch, batch_idx)

    pbar.close()

    me = await client.get_me()
    print(f"Done. Messages: {written}. User: @{me.username or me.id}. Output: {out_path if not batching else str(out_path.parent / (out_path.stem + '_part*.json'))}")
    if media_dir:
        print(f"Media in: {media_dir}")

if __name__ == "__main__":
    asyncio.run(main())