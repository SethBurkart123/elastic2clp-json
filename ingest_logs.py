import os
import json
import fcntl
import sys
import argparse
import subprocess
import signal
import time
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from elastic_search import elastic_search
from setup_clp_json import setup_clp_json, is_clp_json_setup
from merge_archives import merge_archives

CONFIG_FILE = 'indexers.json'
STATE_FILE = 'ingestion_state.json'
MAX_RESULTS = 10000
CONTINUOUS_INTERVAL = 30

shutdown_requested = False

def parse_datetime(date_string):
    """Parse datetime string in various formats"""
    try:
        return datetime.fromisoformat(date_string.replace('Z', '+00:00'))
    except ValueError:
        try:
            return datetime.strptime(date_string, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
        except ValueError:
            try:
                return datetime.strptime(date_string, '%Y-%m-%d').replace(tzinfo=timezone.utc)
            except ValueError:
                raise argparse.ArgumentTypeError(f"Invalid date format: '{date_string}'. Use YYYY-MM-DD or YYYY-MM-DD HH:MM:SS")

def positive_float(value):
    """Validate positive float for interval argument"""
    fvalue = float(value)
    if fvalue <= 0:
        raise argparse.ArgumentTypeError(f"{value} must be positive")
    return fvalue

def load_indexers():
    """Load indexers from JSON config file"""
    if not Path(CONFIG_FILE).exists():
        save_indexers_config({'indexers': []})
        return {}
    
    with open(CONFIG_FILE, 'r') as f:
        config = json.load(f)
    
    if 'indexers' not in config:
        print(f"Error: '{CONFIG_FILE}' must contain an 'indexers' array")
        sys.exit(1)
    
    indexers = {}
    for idx in config['indexers']:
        if 'name' not in idx:
            print(f"Error: Indexer missing 'name' field")
            sys.exit(1)
        
        name = idx['name']
        if name in indexers:
            print(f"Error: Duplicate indexer name '{name}'")
            sys.exit(1)
        
        required = ['host', 'user', 'password']
        for field in required:
            if field not in idx:
                print(f"Error: Indexer '{name}' missing required field '{field}'")
                sys.exit(1)
        
        indexers[name] = {
            'name': name,
            'host': idx['host'],
            'user': idx['user'],
            'password': idx['password'],
            'output_dir': Path(f"./logs/{name}"),
            'interval': idx.get('interval', 20.0),
            'timestamp_key': idx.get('timestamp_key', 'timestamp')
        }
    
    return indexers

def save_indexers_config(config):
    """Save indexers config to JSON file"""
    temp_file = f"{CONFIG_FILE}.tmp"
    with open(temp_file, 'w') as f:
        json.dump(config, f, indent=2)
    os.rename(temp_file, CONFIG_FILE)

def add_indexer(name, host, user, password, interval=20.0, timestamp_key='timestamp'):
    """Add a new indexer to the config file"""
    if Path(CONFIG_FILE).exists():
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)
    else:
        config = {'indexers': []}
    
    if 'indexers' not in config:
        config['indexers'] = []
    
    for idx in config['indexers']:
        if idx.get('name') == name:
            print(f"Error: Indexer '{name}' already exists")
            sys.exit(1)
    
    new_indexer = {
        'name': name,
        'host': host,
        'user': user,
        'password': password,
        'interval': float(interval),
        'timestamp_key': timestamp_key
    }
    
    config['indexers'].append(new_indexer)
    save_indexers_config(config)
    print(f"Added indexer '{name}' successfully")

def load_state():
    """Load last ingestion time from state file (per-indexer)"""
    if Path(STATE_FILE).exists():
        with open(STATE_FILE, 'r') as f:
            state = json.load(f)
            return state.get('indexers', {})
    return {}

def save_state(all_indexer_states):
    """Atomically save state to file (per-indexer)"""
    temp_file = f"{STATE_FILE}.tmp"
    state = {'indexers': all_indexer_states}
    
    with open(f"/tmp/{STATE_FILE}.lock", 'w') as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            with open(temp_file, 'w') as f:
                json.dump(state, f, indent=2)
            os.rename(temp_file, STATE_FILE)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)

def update_indexer_state(indexer_name, last_ingest_time, all_indexer_states):
    """Update state for a specific indexer"""
    all_indexer_states[indexer_name] = {'last_ingest_time': last_ingest_time.isoformat()}
    save_state(all_indexer_states)

def is_indexer_running(indexer_name):
    """Check if an indexer is currently running by attempting to acquire lock"""
    lock_file = f"/tmp/log_ingestion_{indexer_name}.lock"
    if not Path(lock_file).exists():
        return False
    
    try:
        with open(lock_file, 'w') as lock_fd:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return False
    except IOError:
        return True

def acquire_lock(indexer_name):
    """Acquire exclusive lock for a specific indexer"""
    lock_file = f"/tmp/log_ingestion_{indexer_name}.lock"
    lock_fd = open(lock_file, 'w')
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lock_fd, lock_file
    except IOError:
        print(f"Another instance is already running for indexer '{indexer_name}'")
        sys.exit(1)

def release_lock(lock_fd, lock_file):
    """Release lock and clean up lock file"""
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()
        if Path(lock_file).exists():
            os.remove(lock_file)
    except Exception:
        pass

def get_log_filepath(output_dir):
    """Generate log file path with timestamp"""
    return Path(output_dir) / f"logs_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json"

def query_with_splitting(indexer, start_time, end_time, log_file, depth=0):
    """Query a time range, splitting if we hit the limit"""
    hits = elastic_search(indexer['host'], indexer['user'], indexer['password'], start_time, end_time, MAX_RESULTS)
    
    if len(hits) >= MAX_RESULTS - 2:
        duration = end_time - start_time
        if duration.total_seconds() < 1:
            print(f"{'  '*depth}⚠️ Too many logs at {start_time} ({len(hits)} logs)")
            for hit in hits:
                log_file.write(json.dumps(hit["_source"]) + '\n')
            return len(hits)
        
        mid_time = start_time + duration / 2
        print(f"{'  '*depth}↓ Splitting {start_time.strftime('%H:%M:%S')} - {end_time.strftime('%H:%M:%S')}")
        
        total = (query_with_splitting(indexer, start_time, mid_time, log_file, depth+1) +
                query_with_splitting(indexer, mid_time, end_time, log_file, depth+1))
        
        if depth == 0:
            print(f"✓ Total: {total} logs")
        return total
    
    if hits and depth > 0:
        print(f"{'  '*depth}→ {len(hits)} logs")
    
    for hit in hits:
        log_file.write(json.dumps(hit["_source"]) + '\n')
    return len(hits)

def ingest_backwards(indexer, indexer_name, end_time, output_path, interval_minutes, compress=True):
    """Ingest backwards until 5 days of no logs"""
    query_interval = timedelta(minutes=interval_minutes)
    total_logs = 0
    empty_days = 0
    current_time = end_time
    
    with open(output_path, 'w') as log_file:
        while empty_days < 5:
            daily_logs = 0
            day_start = current_time - timedelta(days=1)
            
            while current_time > day_start:
                chunk_start = max(current_time - query_interval, day_start)
                count = query_with_splitting(indexer, chunk_start, current_time, log_file)
                
                if count > 0:
                    print(f"{chunk_start.strftime('%Y-%m-%d %H:%M')} -> {current_time.strftime('%H:%M')}: {count} logs")
                    daily_logs += count
                    total_logs += count
                
                current_time = chunk_start
            
            if daily_logs == 0:
                empty_days += 1
                print(f"No logs found on {current_time.strftime('%Y-%m-%d')} ({empty_days}/5 empty days)")
            else:
                empty_days = 0
    
    if total_logs == 0:
        output_path.unlink()
        print("No logs found. File not created.")
    else:
        print(f"Ingestion complete. Total logs: {total_logs}")
        print(f"Saved to: {output_path}")
        
        if compress:
            compress_to_clp_json(indexer_name, indexer['timestamp_key'], output_path.parent)

def compress_to_clp_json(indexer_name, timestamp_key, output_dir):
    """Compress json files in output_dir to clp-json"""
    if not is_clp_json_setup():
        if not setup_clp_json():
            print("Warning: Failed to setup clp-json. Skipping compression.")
            return False
    
    compress_script = Path("clp-json-x86_64-v0.7.0/sbin/compress.sh")
    if not compress_script.exists():
        print("Warning: clp-json compress.sh not found. Skipping compression.")
        return False
    
    output_path = Path(output_dir)
    json_files = list(output_path.glob("*.json"))
    
    if not json_files:
        return False
    
    try:
        subprocess.run(
            [str(compress_script), '--timestamp-key', timestamp_key, '--dataset', indexer_name, str(output_dir)],
            check=True
        )
        
        for _ in range(2):
            merge_archives(indexer_name, timestamp_key)
        
        removed_count = 0
        for json_file in json_files:
            if json_file.exists():
                json_file.unlink()
                removed_count += 1
        
        if removed_count > 0:
            print(f"Compressed to clp-json and removed {removed_count} JSON file(s)")
        
        return True
    except subprocess.CalledProcessError as e:
        print(f"Warning: clp-json compression failed: {e}")
        return False

def ingest_forward(indexer, indexer_name, start_time, end_time, output_path, interval_minutes, save_checkpoint=True, compress=True):
    """Ingest forward from start_time to end_time"""
    query_interval = timedelta(minutes=interval_minutes)
    total_logs = 0
    
    with open(output_path, 'w') as log_file:
        while start_time < end_time:
            chunk_end = min(start_time + query_interval, end_time)
            count = query_with_splitting(indexer, start_time, chunk_end, log_file)
            
            if count > 0:
                print(f"{start_time.strftime('%Y-%m-%d %H:%M')} -> {chunk_end.strftime('%H:%M')}: {count} logs")
                total_logs += count
            
            start_time = chunk_end
    
    if total_logs == 0:
        output_path.unlink()
        print("No logs found. File not created.")
    else:
        if save_checkpoint:
            update_indexer_state(indexer_name, end_time, load_state())
        print(f"Ingestion complete. Total logs: {total_logs}")
        print(f"Saved to: {output_path}")
        
        if compress:
            compress_to_clp_json(indexer_name, indexer['timestamp_key'], output_path.parent)

def signal_handler(signum, frame):
    global shutdown_requested
    shutdown_requested = True

def run_indexer(indexer_name, indexer, args, all_indexer_states):
    """Run ingestion for a single indexer"""
    print(f"\n{'='*60}")
    print(f"Indexer: {indexer_name}")
    print(f"Host: {indexer['host']}")
    print(f"Output: {indexer['output_dir']}")
    print(f"{'='*60}\n")
    
    lock_fd, lock_file = acquire_lock(indexer_name)
    
    try:
        current_time = datetime.now(timezone.utc)
        indexer['output_dir'].mkdir(parents=True, exist_ok=True)
        output_path = get_log_filepath(indexer['output_dir'])
        interval = args.interval if args.interval else indexer['interval']
        
        compress = not args.no_clp_json
        
        if args.from_date:
            print(f"Ingesting backwards from {args.from_date.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"Using {interval} minute intervals")
            ingest_backwards(indexer, indexer_name, args.from_date, output_path, interval, compress)
            
        elif args.reset:
            start_time = current_time - timedelta(minutes=20)
            print(f"Reset mode: starting from {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"Using {interval} minute intervals")
            ingest_forward(indexer, indexer_name, start_time, current_time, output_path, interval, True, compress)
            
        else:
            indexer_state = all_indexer_states.get(indexer_name, {})
            if indexer_state.get('last_ingest_time'):
                start_time = datetime.fromisoformat(indexer_state['last_ingest_time'])
                print(f"Continuing from checkpoint: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"Using {interval} minute intervals")
                ingest_forward(indexer, indexer_name, start_time, current_time, output_path, interval, True, compress)
            else:
                print(f"First run for indexer '{indexer_name}': ingesting all previous logs")
                print(f"Using {interval} minute intervals")
                ingest_backwards(indexer, indexer_name, current_time, output_path, interval, compress)
                update_indexer_state(indexer_name, current_time, all_indexer_states)
        
    except Exception as e:
        print(f"Error during ingestion for '{indexer_name}': {e}")
        raise
    finally:
        release_lock(lock_fd, lock_file)

def main():
    parser = argparse.ArgumentParser(
        description='Ingest logs from Elasticsearch (multi-indexer support)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''Examples:
  %(prog)s                              # Continue all indexers from last checkpoint
  %(prog)s --indexer production         # Run only the 'production' indexer
  %(prog)s --list-indexers              # List all configured indexers
  %(prog)s --interval 10                # Query in 10-minute chunks (overrides config)
  %(prog)s --from-date "2024-10-27 12:00:00"  # Go backwards until 5 empty days
  %(prog)s --reset                      # Ignore checkpoint, start from 20 mins ago
  %(prog)s --continuous                 # Run continuously, checking every 30 seconds'''
    )
    
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--from-date', type=parse_datetime, metavar='DATETIME',
                      help='Start from this date/time and go backwards until 5 days without logs')
    mode.add_argument('--reset', action='store_true',
                      help='Ignore checkpoint, start from 20 minutes ago')
    
    parser.add_argument('--indexer', type=str, metavar='NAME',
                        help='Run only the specified indexer (default: run all)')
    parser.add_argument('--list-indexers', action='store_true',
                        help='List all configured indexers and exit')
    parser.add_argument('--interval', type=positive_float, default=None,
                        help='Query interval in minutes (overrides config, can use decimals e.g. 0.5 for 30 seconds)')
    
    parser.add_argument('--add-indexer', action='store_true',
                        help='Add a new indexer (requires --indexer-name, --host, --user, --password). Output directory will be ./logs/{indexer-name}')
    parser.add_argument('--indexer-name', type=str, metavar='NAME',
                        help='Name for the new indexer (used with --add-indexer)')
    parser.add_argument('--host', type=str, metavar='URL',
                        help='Elasticsearch host URL (used with --add-indexer)')
    parser.add_argument('--user', type=str, metavar='USERNAME',
                        help='Elasticsearch username (used with --add-indexer)')
    parser.add_argument('--password', type=str, metavar='PASSWORD',
                        help='Elasticsearch password (used with --add-indexer)')
    parser.add_argument('--timestamp-key', type=str, metavar='KEY',
                        help='Timestamp key field name (used with --add-indexer, default: timestamp). Can be quoted to include spaces.')
    parser.add_argument('--no-clp-json', action='store_true',
                        help='Skip clp-json compression (default: compress to clp-json)')
    parser.add_argument('--continuous', action='store_true',
                        help='Run continuously, checking every 30 seconds if ingestion is finished')
    
    args = parser.parse_args()
    
    if args.add_indexer:
        if not all([args.indexer_name, args.host, args.user, args.password]):
            print("Error: --add-indexer requires --indexer-name, --host, --user, and --password")
            sys.exit(1)
        interval = args.interval if args.interval else 20.0
        timestamp_key = args.timestamp_key if args.timestamp_key else 'timestamp'
        add_indexer(args.indexer_name, args.host, args.user, args.password, interval, timestamp_key)
        sys.exit(0)
    
    indexers = load_indexers()
    
    if args.list_indexers:
        print("Configured indexers:")
        for name, idx in indexers.items():
            print(f"  - {name}")
            print(f"    Host: {idx['host']}")
            print(f"    Output: {idx['output_dir']}")
            print(f"    Interval: {idx['interval']} minutes")
        sys.exit(0)
    
    all_indexer_states = load_state()
    
    if args.indexer:
        if args.indexer not in indexers:
            print(f"Error: Indexer '{args.indexer}' not found in config")
            if indexers:
                print(f"Available indexers: {', '.join(indexers.keys())}")
            else:
                print("No indexers configured. Use --add-indexer to add one.")
            sys.exit(1)
        indexers_to_run = {args.indexer: indexers[args.indexer]}
    else:
        indexers_to_run = indexers
    
    if not indexers_to_run:
        print("Error: No indexers configured. Use --add-indexer to add one.")
        sys.exit(1)
    
    if args.continuous:
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
        
        print("Running in continuous mode. Checking every 30 seconds...")
        print("Press Ctrl+C or send SIGTERM to stop.\n")
        
        last_run_times = {}
        
        while not shutdown_requested:
            try:
                current_indexers = load_indexers()
            except (json.JSONDecodeError, KeyError) as e:
                print(f"Error loading indexers config: {e}. Retrying in {CONTINUOUS_INTERVAL} seconds...")
                time.sleep(CONTINUOUS_INTERVAL)
                continue
            
            if args.indexer:
                if args.indexer not in current_indexers:
                    print(f"Warning: Indexer '{args.indexer}' not found in config, skipping this cycle")
                    time.sleep(CONTINUOUS_INTERVAL)
                    continue
                indexers_to_run = {args.indexer: current_indexers[args.indexer]}
            else:
                indexers_to_run = current_indexers
            
            if not indexers_to_run:
                print("No indexers configured. Waiting for indexers to be added...")
                time.sleep(CONTINUOUS_INTERVAL)
                continue
            
            all_indexer_states = load_state()
            
            for indexer_name, indexer in indexers_to_run.items():
                if shutdown_requested:
                    break
                
                if is_indexer_running(indexer_name):
                    continue
                
                if time.time() - last_run_times.get(indexer_name, 0) >= CONTINUOUS_INTERVAL:
                    last_run_times[indexer_name] = time.time()
                    threading.Thread(
                        target=run_indexer,
                        args=(indexer_name, indexer, args, all_indexer_states),
                        daemon=True
                    ).start()
            
            if not shutdown_requested:
                time.sleep(CONTINUOUS_INTERVAL)
        
        print("\nShutting down gracefully...")
        for thread in [t for t in threading.enumerate() if t != threading.current_thread() and t.is_alive()]:
            thread.join(timeout=5)
    else:
        for indexer_name, indexer in indexers_to_run.items():
            try:
                run_indexer(indexer_name, indexer, args, all_indexer_states)
            except Exception as e:
                print(f"Failed to process indexer '{indexer_name}': {e}")
                if len(indexers_to_run) == 1:
                    sys.exit(1)
                continue

if __name__ == "__main__":
    main()
