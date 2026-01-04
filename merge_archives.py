#!/usr/bin/env python3
"""
merge_archives.py - Merge small CLP archives together
"""

import sys
import json
import yaml
import subprocess
import shutil
import fcntl
import os
from pathlib import Path
from datetime import datetime

import pymysql

SCRIPT_DIR = Path(__file__).parent.resolve()
CLP_JSON_DIR = SCRIPT_DIR / "clp-json-x86_64-v0.7.0"
INDEXERS_FILE = SCRIPT_DIR / "indexers.json"
DEFAULT_SIZE_THRESHOLD = 134217728  # 128 MB
DEFAULT_TIMESTAMP_KEY = "timestamp"


def load_config():
    config_path = CLP_JSON_DIR / "etc" / "clp-config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def load_credentials():
    creds_path = CLP_JSON_DIR / "etc" / "credentials.yaml"
    with open(creds_path) as f:
        return yaml.safe_load(f)


def get_stream_output_dir(dataset):
    merge_dir = SCRIPT_DIR / "merge" / dataset
    merge_dir.mkdir(parents=True, exist_ok=True)
    return merge_dir


def get_timestamp_key_from_indexers(dataset):
    if not INDEXERS_FILE.exists():
        return DEFAULT_TIMESTAMP_KEY
    with open(INDEXERS_FILE, 'r') as f:
        config = json.load(f)
    for idx in config.get('indexers', []):
        if idx.get('name') == dataset:
            return idx.get('timestamp_key', DEFAULT_TIMESTAMP_KEY)
    return DEFAULT_TIMESTAMP_KEY


def get_db_connection():
    config = load_config()
    creds = load_credentials()
    db_config = config.get("database", {})
    return pymysql.connect(
        host=db_config.get("host", "localhost"),
        port=db_config.get("port", 3306),
        user=creds["database"]["username"],
        password=creds["database"]["password"],
        database=db_config.get("name", "clp-db")
    )


def get_smallest_archives(dataset, size_threshold):
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT name FROM `clp_datasets` WHERE name = %s", (dataset,))
            if not cursor.fetchone():
                return None

            archives_table = f"`clp_{dataset}_archives`"
            cursor.execute(f"""
                SELECT id, size, uncompressed_size 
                FROM {archives_table}
                WHERE uncompressed_size > 0
                ORDER BY uncompressed_size ASC
                LIMIT 2
            """)
            archives = cursor.fetchall()

            if len(archives) < 2:
                return None

            if archives[0][2] + archives[1][2] >= size_threshold:
                return None

            return [
                {"id": archives[0][0], "size": archives[0][1], "uncompressed_size": archives[0][2]},
                {"id": archives[1][0], "size": archives[1][1], "uncompressed_size": archives[1][2]}
            ]
    finally:
        conn.close()


def extract_archive(archive_id, dataset):
    decompress_script = CLP_JSON_DIR / "sbin" / "decompress.sh"
    config_path = CLP_JSON_DIR / "etc" / "clp-config.yaml"
    stream_output_dir = get_stream_output_dir(dataset)
    
    for item in stream_output_dir.iterdir():
        if item.is_file():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)
    
    with open(config_path, 'r') as f:
        config_content = yaml.safe_load(f)
    
    config_content["stream_output"]["storage"]["directory"] = str(stream_output_dir)
    temp_config = config_path.with_suffix('.yaml.tmp')
    with open(temp_config, 'w') as f:
        yaml.dump(config_content, f)
    
    try:
        result = subprocess.run(
            [str(decompress_script), "-c", str(temp_config), "j", str(archive_id), "--dataset", dataset],
            cwd=CLP_JSON_DIR,
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            print(f"Error extracting archive {archive_id}: {result.stderr}")
            return None
        
        json_files = list(stream_output_dir.glob("*.json"))
        json_files.extend(stream_output_dir.glob("*.jsonl"))
        
        for subdir in stream_output_dir.iterdir():
            if subdir.is_dir():
                json_files.extend(subdir.glob("*.json"))
                json_files.extend(subdir.glob("*.jsonl"))
        
        return json_files
    finally:
        if temp_config.exists():
            temp_config.unlink()


def compress_files(input_file, dataset, timestamp_key):
    compress_script = CLP_JSON_DIR / "sbin" / "compress.sh"
    config_path = CLP_JSON_DIR / "etc" / "clp-config.yaml"
    
    result = subprocess.run(
        [str(compress_script), "-c", str(config_path), "--timestamp-key", timestamp_key, "--dataset", dataset, str(input_file)],
        cwd=CLP_JSON_DIR,
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        print(f"Error compressing files: {result.stderr}")
        return False
    return True


def delete_archives(dataset, archive_ids):
    archive_manager = CLP_JSON_DIR / "sbin" / "admin-tools" / "archive-manager.sh"
    config_path = CLP_JSON_DIR / "etc" / "clp-config.yaml"
    
    result = subprocess.run(
        [str(archive_manager), "-c", str(config_path), "--dataset", dataset, "del", "by-ids"] + list(archive_ids),
        cwd=CLP_JSON_DIR,
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        print(f"Error deleting archives: {result.stderr}")
        return False
    return True


def merge_archives(dataset, timestamp_key, size_threshold=DEFAULT_SIZE_THRESHOLD):
    lock_file = f"/tmp/merge_archives_{dataset}.lock"
    lock_fd = open(lock_file, 'w')
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        lock_fd.close()
        return False
    
    try:
        archives = get_smallest_archives(dataset, size_threshold)
        if not archives:
            return False
        
        print(f"Merging archives {archives[0]['id']} and {archives[1]['id']}")
        
        temp_dir = CLP_JSON_DIR / "var" / "tmp" / f"merge_{dataset}_{os.getpid()}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        combined_file = temp_dir / "combined.json"
        
        try:
            with open(combined_file, 'w') as outf:
                for archive in archives:
                    json_files = extract_archive(archive["id"], dataset)
                    if json_files is None:
                        return False
                    for json_file in json_files:
                        with open(json_file, 'r') as inf:
                            for line in inf:
                                if line.strip():
                                    outf.write(line.strip() + '\n')
            
            if not compress_files(combined_file, dataset, timestamp_key):
                return False
            
            if not delete_archives(dataset, [a["id"] for a in archives]):
                return False
            
            print(f"Successfully merged and deleted archives {archives[0]['id']} and {archives[1]['id']}")
            return True
        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()
        if Path(lock_file).exists():
            os.remove(lock_file)


def main():
    if len(sys.argv) < 2:
        print("Usage: merge_archives.py <dataset> [timestamp_key] [size_threshold]")
        sys.exit(1)
    
    dataset = sys.argv[1]
    timestamp_key = sys.argv[2] if len(sys.argv) >= 3 else get_timestamp_key_from_indexers(dataset)
    size_threshold = int(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_SIZE_THRESHOLD
    
    success = merge_archives(dataset, timestamp_key, size_threshold)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
