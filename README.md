# ChatLoader

A command-line tool to export Telegram chat or group history into JSONL files.  
Optionally downloads attached media and supports batching, retry logic, and rate limiting.

## Features
- Export messages from any chat, channel, or group.
- Save messages as JSONL (one message per line).
- Batch writing to multiple files.
- Download attached media (photos, videos, documents).
- Configurable retries, backoff, and rate limiting.
- Supports both user sessions and bot tokens.

## Requirements
- Python 3.8+
- A Telegram API ID and API Hash (get them from [my.telegram.org](https://my.telegram.org)).

## Installation
```bash
git clone https://github.com/yourname/ChatLoader.git
cd ChatLoader
pip install -r requirements.txt
```

## Usage
```bash
python dump_telegram_history.py --chat <CHAT_ID_OR_USERNAME> [options]
```

### Arguments
- `--chat` *(required)*: Chat @username, invite link, or numeric ID.  
- `--json`: Output file path (default: `messages.jsonl`).  
- `--media-dir`: Directory to download media.  
- `--reverse`: Export oldest → newest.  
- `--limit`: Maximum number of messages.  
- `--as-bot-token`: Authenticate with bot token instead of user.  
- `--batch-size`: Write messages in batches of this size into `*_partNNNNN.json`.  

### Rate Limiting / Backoff Options
- `--sleep-per-msg`: Seconds to sleep after each message.  
- `--sleep-every`: Sleep every N messages.  
- `--sleep-seconds`: Seconds to sleep when triggered.  
- `--max-retries`: Max retries for media downloads.  
- `--retry-backoff`: Initial backoff multiplier.  
- `--flood-threshold`: Auto-sleep for FloodWait errors below this threshold.  

## Example
```bash
python dump_telegram_history.py
--chat "@mychannel"
--json "history.jsonl"
--media-dir "media"
--batch-size 1000
```

Output:
- `history.jsonl` or multiple files like `history_part00001.json`.
- Media saved in the given directory.

## License
MIT

