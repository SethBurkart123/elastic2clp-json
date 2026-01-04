# elastic2clp-json

A robust Elasticsearch log ingestion tool that efficiently extracts logs from Elasticsearch and directly compresses them into CLP-JSON archives with automatic archive joining support. Supports multiple indexers with independent configuration, state tracking, and output paths.

## Features

- **Multi-indexer support** - Manage multiple Elasticsearch sources independently
- **Per-indexer state tracking** - Each indexer maintains its own checkpoint
- **Per-indexer locking** - Prevent concurrent runs per indexer
- **Stateful ingestion** - Automatically resume from where you left off for each indexer
- **Flexible time-based ingestion modes** - Forward from checkpoint, backward from date, or reset
- **Configurable query intervals** - Set per-indexer or override via CLI (from seconds to hours)
- **CLI indexer management** - Add new indexers from the command line
- **Direct CLP-JSON compression** - Automatically compresses ingested logs to CLP-JSON archives
- **Archive joining support** - Automatically merges small archives to optimize storage
- **Timestamped output files** - Organized log storage with automatic directory creation
- **Atomic state management** - Prevent data loss on failures
- **Smart result limit detection** - Automatically splits queries when hitting Elasticsearch limits

## Requirements

- Python 3.10+
- Linux/macOS (uses fcntl for file locking)
- Access to Elasticsearch instance(s)
- `uv` package manager (or standard pip)

## Installation

Clone the repository:
```bash
git clone https://github.com/SethBurkart123/elastic2clp-json.git
cd elastic2clp-json
```

Install dependencies:
```bash
uv sync
```

### 2. Setup CLP-JSON (Required for Compression)

Before running ingestion, you must set up CLP-JSON. This only needs to be done once and requires sudo access:

```bash
uv run setup_clp_json.py
```

This will:
- Install system dependencies (wget, tar, Docker if needed)
- Download and extract CLP-JSON
- Configure CLP-JSON services
- Set up Docker group permissions

**Note**: You will be prompted for your sudo password during setup. On Linux, you may need to log out and back in after setup for Docker group changes to take effect.

## Quick Start

### 1. Add Your First Indexer

```bash
uv run ingest_logs.py --add-indexer \
  --indexer-name production \
  --host http://your-elasticsearch:9200/*/_search \
  --user your_username \
  --password your_password \
  --output-dir ./logs/production \
  --interval 20.0
```

### 2. Run Ingestion

```bash
# Run all configured indexers (one-time)
uv run ingest_logs.py

# Or run continuously (recommended for production)
uv run ingest_logs.py --continuous

# Or run a specific indexer
uv run ingest_logs.py --indexer production
```

**First-time behavior**: On the first run for each indexer, the tool automatically ingests all previous logs (going backwards until 5 days without logs), then saves a checkpoint. Subsequent runs only ingest new logs from that checkpoint forward.

## Configuration

### JSON Configuration File

Indexers are configured in `indexers.json`. The file is automatically created when you add your first indexer via CLI, or you can create it manually:

```json
{
  "indexers": [
    {
      "name": "production",
      "host": "http://prod-es:9200/*/_search",
      "user": "prod_user",
      "password": "prod_pass",
      "interval": 20.0
    },
    {
      "name": "staging",
      "host": "http://stage-es:9200/*/_search",
      "user": "stage_user",
      "password": "stage_pass",
      "interval": 30.0
    }
  ]
}
```

**Fields:**
- `name` (required) - Unique identifier for the indexer
- `host` (required) - Elasticsearch search endpoint URL (include `/*/_search` pattern)
- `user` (required) - Elasticsearch username
- `password` (required) - Elasticsearch password
- `interval` (optional) - Query interval in minutes (default: 20.0)
- `timestamp_key` (optional) - Field name for timestamps in log documents (default: "timestamp")

### Managing Indexers

#### Add a New Indexer via CLI

```bash
uv run ingest_logs.py --add-indexer \
  --indexer-name myindexer \
  --host http://es:9200/*/_search \
  --user username \
  --password password \
  --output-dir ./logs/myindexer \
  --interval 15.0 \
  --timestamp-key timestamp
```

#### List Configured Indexers

```bash
uv run ingest_logs.py --list-indexers
```

## Usage

### Command Line Options

```
usage: ingest_logs.py [-h] [--from-date DATETIME | --reset] [--indexer NAME] 
                      [--list-indexers] [--interval MINUTES] [--no-clp-json]
                      [--add-indexer] [--indexer-name NAME] [--host URL] 
                      [--user USERNAME] [--password PASSWORD] [--output-dir DIR]
                      [--timestamp-key KEY]

Ingest logs from Elasticsearch and compress to CLP-JSON (multi-indexer support)

optional arguments:
  -h, --help            show this help message and exit
  --from-date DATETIME  Start from this date/time and go backwards until 5 empty days
  --reset               Ignore checkpoint, start from 20 minutes ago
  --indexer NAME        Run only the specified indexer (default: run all)
  --list-indexers       List all configured indexers and exit
  --interval MINUTES    Query interval in minutes (overrides config, can use decimals e.g. 0.5 for 30 seconds)
  --no-clp-json         Skip CLP-JSON compression (default: compress to CLP-JSON)
  --add-indexer         Add a new indexer (requires --indexer-name, --host, --user, --password, --output-dir)
  --indexer-name NAME   Name for the new indexer (used with --add-indexer)
  --host URL            Elasticsearch host URL (used with --add-indexer)
  --user USERNAME       Elasticsearch username (used with --add-indexer)
  --password PASSWORD   Elasticsearch password (used with --add-indexer)
  --output-dir DIR      Output directory for logs (used with --add-indexer)
  --timestamp-key KEY   Timestamp key field name (used with --add-indexer, default: timestamp)
```

### Examples

#### Standard Operation

Continue all indexers from their last checkpoints (or ingest all previous logs on first run):
```bash
uv run ingest_logs.py
```

Run only a specific indexer:
```bash
uv run ingest_logs.py --indexer production
```

#### Custom Query Intervals

Override the configured interval (applies to all indexers run):
```bash
# 10-minute chunks
uv run ingest_logs.py --interval 10

# 30-second chunks (for high-volume periods)
uv run ingest_logs.py --interval 0.5

# 1-hour chunks (for historical data)
uv run ingest_logs.py --interval 60
```

#### Historical Data Ingestion

Go backward from a specific date until 5 days without logs:
```bash
# From specific date and time
uv run ingest_logs.py --from-date "2024-10-27 12:00:00"

# From midnight of a date
uv run ingest_logs.py --from-date "2024-10-27"

# For a specific indexer
uv run ingest_logs.py --indexer production --from-date "2024-10-27"
```

#### Reset Mode

Ignore checkpoint and start from 20 minutes ago:
```bash
# Reset all indexers
uv run ingest_logs.py --reset

# Reset specific indexer
uv run ingest_logs.py --indexer production --reset
```

#### Continuous Mode

Run continuously, checking every 30 seconds for new logs:
```bash
# Run all indexers continuously
uv run ingest_logs.py --continuous

# Run a specific indexer continuously
uv run ingest_logs.py --indexer production --continuous
```

In continuous mode, the script will:
- Check every 30 seconds if ingestion is needed
- Automatically run ingestion for each indexer when new logs are available
- Run each indexer in a separate thread to allow parallel processing
- Gracefully handle shutdown signals (Ctrl+C or SIGTERM)

**Note**: CLP-JSON must be set up before running in continuous mode. Run `uv run setup_clp_json.py` first.

#### Skip CLP-JSON Compression

Save logs as JSON files without compressing to CLP-JSON:
```bash
uv run ingest_logs.py --no-clp-json
```

#### Combine Options

```bash
# Historical data with custom interval
uv run ingest_logs.py --from-date "2024-10-25" --interval 5

# Reset with custom interval for specific indexer
uv run ingest_logs.py --indexer staging --reset --interval 30
```

## How It Works

1. **Multi-Indexer Architecture**: Each indexer is configured independently with its own host, credentials, output directory, and query interval.

2. **First-Time vs. Subsequent Runs**: 
   - **First run**: Automatically ingests all previous logs (backwards until 5 days without logs), then saves a checkpoint
   - **Subsequent runs**: Only ingests new logs from the last checkpoint forward
   - Prevents duplicate logs by using exclusive time ranges (`[start, end)`)

3. **Per-Indexer State Management**: The tool maintains state in `ingestion_state.json` with separate timestamps for each indexer:
   ```json
   {
     "indexers": {
       "production": {"last_ingest_time": "2024-10-27T13:04:52.123456+00:00"},
       "staging": {"last_ingest_time": "2024-10-27T12:30:15.654321+00:00"}
     }
   }
   ```

4. **Per-Indexer Locking**: Uses file locking (`/tmp/log_ingestion_{indexer_name}.lock`) to prevent multiple instances from running the same indexer simultaneously. Different indexers can run concurrently.

5. **Query Strategy**: Breaks large time ranges into smaller chunks (configurable per indexer) to avoid Elasticsearch query limits. Automatically splits queries when hitting the 10,000 result limit.

6. **Error Handling**: If ingestion fails, the state file isn't updated for that indexer, allowing the next run to retry from the same point.

7. **CLP-JSON Compression**: After ingestion, logs are automatically compressed to CLP-JSON archives. The tool runs archive merging twice to combine small archives, optimizing storage. JSON files are automatically removed after successful compression.

8. **Output Format**: Logs are temporarily saved as JSON files with timestamped filenames like `logs_2024-10-27_13-04-52.json` in each indexer's output directory, then compressed to CLP-JSON archives and removed.

## Output Files

- **CLP-JSON archives**: Compressed archives stored in CLP-JSON's configured storage (see `clp-config.yaml`)
- **Temporary JSON files**: `logs_YYYY-MM-DD_HH-MM-SS.json` in each indexer's output directory (removed after compression)
- **State file**: `ingestion_state.json` - Tracks last successful ingestion time per indexer
- **Lock files**: `/tmp/log_ingestion_{indexer_name}.lock` - Prevents concurrent execution (automatically cleaned up)
- **Config file**: `indexers.json` - Indexer configurations

## Files to Add to .gitignore

```
indexers.json
ingestion_state.json
ingestion_state.json.tmp
logs_*.json
*.json
clp-json-x86_64-v0.7.0/
```

## Troubleshooting

**"CLP-JSON is not set up"**: Run `uv run setup_clp_json.py` first. This only needs to be done once and requires sudo access.

**"No indexers configured"**: Add an indexer using `--add-indexer` or create `indexers.json` manually.

**"Another instance is already running for indexer '{name}'"**: Check if another process is running that indexer, or manually remove `/tmp/log_ingestion_{name}.lock` if a previous run crashed.

**"Indexer '{name}' not found in config"**: Use `--list-indexers` to see configured indexers, or add it with `--add-indexer`.

**"Hit result limit"**: The tool warns when hitting the 10,000 result limit and automatically splits queries. For high-volume periods, use smaller `--interval` values or configure a smaller interval in `indexers.json`.

**Missing logs**: Check `ingestion_state.json` to see the last successful ingestion time for each indexer. Use `--reset` or `--from-date` to re-ingest if needed.

**HTTP errors from Elasticsearch**: Check your Elasticsearch host URL, credentials, and network connectivity.

**Docker permission errors**: After running `setup_clp_json.py`, you may need to log out and back in for Docker group changes to take effect. Alternatively, run `newgrp docker` in your current shell.