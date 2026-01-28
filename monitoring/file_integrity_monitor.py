#!/usr/bin/env python3
"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
File Integrity Monitor
Purpose: Detect unauthorized file modifications (AIDE-style)
"""

import os
import sys
import json
import hashlib
import time
from datetime import datetime
from pathlib import Path


class FileIntegrityMonitor:
    """
    File Integrity Monitoring System
    - Creates SHA256 hash baseline of critical files
    - Detects modifications
    - Alerts on changes
    """

    def __init__(self, baseline_path='/app/monitoring/baseline.json'):
        self.baseline_path = baseline_path
        self.watched_paths = [
            '/app',
            '/etc/nginx',
            '/etc/tor'
        ]
        self.exclude_patterns = [
            '__pycache__',
            '.pyc',
            '.log',
            '.db',
            'baseline.json'
        ]

    def should_exclude(self, filepath):
        """Check if file should be excluded"""
        filepath_str = str(filepath)
        return any(pattern in filepath_str for pattern in self.exclude_patterns)

    def hash_file(self, filepath):
        """Calculate SHA256 hash of file"""
        sha256_hash = hashlib.sha256()
        try:
            with open(filepath, 'rb') as f:
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(byte_block)
            return sha256_hash.hexdigest()
        except Exception as e:
            print(f"Error hashing {filepath}: {e}")
            return None

    def create_baseline(self):
        """Create baseline of file hashes"""
        print("[*] Creating file integrity baseline...")

        baseline = {}
        file_count = 0

        for watched_path in self.watched_paths:
            if not os.path.exists(watched_path):
                print(f"[!] Warning: Path does not exist: {watched_path}")
                continue

            for root, dirs, files in os.walk(watched_path):
                for file in files:
                    filepath = Path(root) / file

                    if self.should_exclude(filepath):
                        continue

                    file_hash = self.hash_file(filepath)
                    if file_hash:
                        baseline[str(filepath)] = {
                            'hash': file_hash,
                            'size': os.path.getsize(filepath),
                            'mtime': os.path.getmtime(filepath)
                        }
                        file_count += 1

        # Save baseline
        with open(self.baseline_path, 'w') as f:
            json.dump({
                'created_at': datetime.utcnow().isoformat(),
                'file_count': file_count,
                'files': baseline
            }, f, indent=2)

        print(f"[+] Baseline created: {file_count} files")
        return baseline

    def load_baseline(self):
        """Load baseline from file"""
        if not os.path.exists(self.baseline_path):
            print(f"[!] Baseline not found: {self.baseline_path}")
            return None

        with open(self.baseline_path, 'r') as f:
            data = json.load(f)
            return data['files']

    def check_integrity(self):
        """Check file integrity against baseline"""
        print("[*] Checking file integrity...")

        baseline = self.load_baseline()
        if not baseline:
            print("[!] No baseline found. Create one with --baseline")
            return False

        changes = {
            'modified': [],
            'added': [],
            'deleted': []
        }

        # Check existing files
        current_files = set()
        for watched_path in self.watched_paths:
            if not os.path.exists(watched_path):
                continue

            for root, dirs, files in os.walk(watched_path):
                for file in files:
                    filepath = Path(root) / file

                    if self.should_exclude(filepath):
                        continue

                    filepath_str = str(filepath)
                    current_files.add(filepath_str)

                    current_hash = self.hash_file(filepath)
                    if not current_hash:
                        continue

                    # Check if file is in baseline
                    if filepath_str in baseline:
                        baseline_hash = baseline[filepath_str]['hash']
                        if current_hash != baseline_hash:
                            changes['modified'].append({
                                'file': filepath_str,
                                'old_hash': baseline_hash,
                                'new_hash': current_hash
                            })
                    else:
                        # New file
                        changes['added'].append(filepath_str)

        # Check for deleted files
        baseline_files = set(baseline.keys())
        deleted_files = baseline_files - current_files
        changes['deleted'] = list(deleted_files)

        # Report changes
        has_changes = any([changes['modified'], changes['added'], changes['deleted']])

        if has_changes:
            print("\n[!] INTEGRITY CHECK FAILED - Changes detected:")
            print(f"    Modified: {len(changes['modified'])}")
            print(f"    Added: {len(changes['added'])}")
            print(f"    Deleted: {len(changes['deleted'])}")

            if changes['modified']:
                print("\n[!] Modified files:")
                for change in changes['modified'][:10]:  # Show first 10
                    print(f"    - {change['file']}")

            if changes['added']:
                print("\n[+] Added files:")
                for file in changes['added'][:10]:
                    print(f"    + {file}")

            if changes['deleted']:
                print("\n[-] Deleted files:")
                for file in changes['deleted'][:10]:
                    print(f"    - {file}")

            # Save report
            report_path = '/var/log/marketplace/fim_report.json'
            os.makedirs(os.path.dirname(report_path), exist_ok=True)
            with open(report_path, 'w') as f:
                json.dump({
                    'timestamp': datetime.utcnow().isoformat(),
                    'changes': changes
                }, f, indent=2)

            return False
        else:
            print("[+] Integrity check PASSED - No changes detected")
            return True

    def monitor_continuous(self, interval=3600):
        """Run continuous monitoring"""
        print(f"[*] Starting continuous monitoring (interval: {interval}s)")

        while True:
            try:
                self.check_integrity()
                time.sleep(interval)
            except KeyboardInterrupt:
                print("\n[*] Monitoring stopped")
                break
            except Exception as e:
                print(f"[!] Error during monitoring: {e}")
                time.sleep(interval)


def main():
    """Main function"""
    import argparse

    parser = argparse.ArgumentParser(description='File Integrity Monitor')
    parser.add_argument('--baseline', action='store_true',
                       help='Create new baseline')
    parser.add_argument('--check', action='store_true',
                       help='Check integrity against baseline')
    parser.add_argument('--monitor', action='store_true',
                       help='Run continuous monitoring')
    parser.add_argument('--interval', type=int, default=3600,
                       help='Monitoring interval in seconds (default: 3600)')

    args = parser.parse_args()

    fim = FileIntegrityMonitor()

    if args.baseline:
        fim.create_baseline()
    elif args.check:
        fim.check_integrity()
    elif args.monitor:
        fim.monitor_continuous(args.interval)
    else:
        parser.print_help()


if __name__ == '__main__':
    print("""
    ╔════════════════════════════════════════════════════════════╗
    ║  EDUCATIONAL SECURITY TRAINING ENVIRONMENT                 ║
    ║  File Integrity Monitor                                    ║
    ║  Purpose: Detect unauthorized file modifications           ║
    ╚════════════════════════════════════════════════════════════╝
    """)
    main()
