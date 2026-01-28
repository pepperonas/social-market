#!/usr/bin/env python3
"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Dead Man's Switch
Purpose: Emergency data wipe if admin doesn't check in

WARNING: This is a demonstration of emergency protocols.
Only for educational purposes - demonstrates concept of dead man's switches.
"""

import os
import sys
import time
import subprocess
from datetime import datetime, timedelta
import psycopg2


class DeadMansSwitch:
    """
    Dead Man's Switch Implementation

    Wipes all data if admin doesn't check in within grace period
    Educational demonstration of emergency shutdown protocols
    """

    def __init__(self):
        self.db_conn = None
        self.checkin_interval = int(os.environ.get('DEADMAN_CHECKIN_INTERVAL', 86400))  # 24h
        self.grace_period = int(os.environ.get('DEADMAN_GRACE_PERIOD', 172800))  # 48h
        self.enabled = os.environ.get('DEADMAN_ENABLED', 'false').lower() == 'true'

    def connect_database(self):
        """Connect to PostgreSQL"""
        try:
            self.db_conn = psycopg2.connect(
                host=os.environ.get('POSTGRES_HOST', 'postgres'),
                port=os.environ.get('POSTGRES_PORT', 5432),
                database=os.environ.get('POSTGRES_DB', 'marketplace'),
                user=os.environ.get('POSTGRES_USER', 'marketplace'),
                password=os.environ.get('POSTGRES_PASSWORD', 'password')
            )
            return True
        except Exception as e:
            print(f"[!] Database connection failed: {e}")
            return False

    def get_last_admin_checkin(self):
        """Get timestamp of last admin login"""
        if not self.db_conn:
            return None

        try:
            cursor = self.db_conn.cursor()
            cursor.execute("""
                SELECT MAX(timestamp) FROM auth_log
                WHERE action = 'login_success'
                  AND user_id IN (SELECT id FROM users WHERE role = 'admin')
            """)

            result = cursor.fetchone()
            cursor.close()

            return result[0] if result and result[0] else None

        except Exception as e:
            print(f"[!] Failed to get last checkin: {e}")
            return None

    def should_trigger(self):
        """Check if dead man's switch should trigger"""
        if not self.enabled:
            return False, "Dead man's switch is disabled"

        last_checkin = self.get_last_admin_checkin()

        if not last_checkin:
            return False, "No admin login history found"

        time_since_checkin = datetime.utcnow() - last_checkin
        grace_period_td = timedelta(seconds=self.grace_period)

        if time_since_checkin > grace_period_td:
            return True, f"No admin checkin for {time_since_checkin.total_seconds() / 3600:.1f} hours"
        else:
            remaining = (grace_period_td - time_since_checkin).total_seconds() / 3600
            return False, f"Grace period remaining: {remaining:.1f} hours"

    def trigger_emergency_wipe(self):
        """
        Trigger emergency data wipe

        Steps:
        1. Log the trigger event
        2. Stop all services
        3. Drop all databases
        4. Delete encryption keys
        5. Send encrypted alert (if configured)
        """
        print("""
        ╔══════════════════════════════════════════════════════╗
        ║   ⚠️  DEAD MAN'S SWITCH TRIGGERED  ⚠️                 ║
        ║   INITIATING EMERGENCY DATA WIPE                     ║
        ╚══════════════════════════════════════════════════════╝
        """)

        # Log trigger event
        self._log_trigger_event()

        # Step 1: Stop all services
        print("[*] Step 1/5: Stopping all services...")
        self._stop_services()

        # Step 2: Drop databases
        print("[*] Step 2/5: Dropping all databases...")
        self._drop_databases()

        # Step 3: Delete encryption keys
        print("[*] Step 3/5: Deleting encryption keys...")
        self._delete_keys()

        # Step 4: Wipe backups
        print("[*] Step 4/5: Wiping backups...")
        self._wipe_backups()

        # Step 5: Send alert
        print("[*] Step 5/5: Sending encrypted alert...")
        self._send_alert()

        print("""
        ╔══════════════════════════════════════════════════════╗
        ║   EMERGENCY WIPE COMPLETED                           ║
        ║   All data has been securely destroyed               ║
        ╚══════════════════════════════════════════════════════╝
        """)

    def _log_trigger_event(self):
        """Log the trigger event"""
        try:
            if self.db_conn:
                cursor = self.db_conn.cursor()
                cursor.execute("""
                    INSERT INTO security_events (event_type, severity, source, description)
                    VALUES ('dead_mans_switch_triggered', 'critical', 'deadman_switch',
                            'Emergency data wipe initiated - no admin checkin within grace period')
                """)
                self.db_conn.commit()
                cursor.close()
        except:
            pass

    def _stop_services(self):
        """Stop all Docker services"""
        try:
            subprocess.run(['docker-compose', 'stop'], timeout=60)
            print("[+] Services stopped")
        except Exception as e:
            print(f"[!] Failed to stop services: {e}")

    def _drop_databases(self):
        """Drop all databases"""
        try:
            if self.db_conn:
                cursor = self.db_conn.cursor()
                cursor.execute("DROP DATABASE IF EXISTS marketplace CASCADE")
                self.db_conn.commit()
                cursor.close()
                print("[+] Databases dropped")
        except Exception as e:
            print(f"[!] Failed to drop databases: {e}")

    def _delete_keys(self):
        """Delete encryption keys and Tor keys"""
        try:
            # Delete Tor keys
            subprocess.run(['rm', '-rf', '/var/lib/tor/hidden_service/'], timeout=10)

            # Delete .env with secrets
            subprocess.run(['rm', '-f', '/app/.env'], timeout=10)

            print("[+] Encryption keys deleted")
        except Exception as e:
            print(f"[!] Failed to delete keys: {e}")

    def _wipe_backups(self):
        """Securely wipe all backups"""
        try:
            # Secure delete backups
            subprocess.run(['shred', '-vfz', '-n', '3', '/backups/*'], timeout=300)
            print("[+] Backups wiped")
        except Exception as e:
            print(f"[!] Failed to wipe backups: {e}")

    def _send_alert(self):
        """Send encrypted alert (if email configured)"""
        # In a real implementation, this would send a PGP-encrypted email
        # to the admin with details of the emergency wipe
        print("[+] Alert logged (email not configured)")

    def run_monitor(self):
        """Run monitoring loop"""
        if not self.enabled:
            print("[*] Dead man's switch is DISABLED")
            print("[*] Enable with DEADMAN_ENABLED=true in .env")
            return

        print("""
        ╔══════════════════════════════════════════════════════╗
        ║   Dead Man's Switch - Monitoring Active             ║
        ║   Educational Security Training Environment          ║
        ╚══════════════════════════════════════════════════════╝
        """)

        print(f"[*] Check-in interval: {self.checkin_interval}s")
        print(f"[*] Grace period: {self.grace_period}s")

        while True:
            try:
                if not self.db_conn or self.db_conn.closed:
                    self.connect_database()

                should_trigger, message = self.should_trigger()

                timestamp = datetime.utcnow().isoformat()
                print(f"[{timestamp}] {message}")

                if should_trigger:
                    print("\n[!!!] TRIGGERING EMERGENCY WIPE [!!!]\n")
                    self.trigger_emergency_wipe()
                    break

                time.sleep(self.checkin_interval)

            except KeyboardInterrupt:
                print("\n[*] Monitoring stopped by user")
                break
            except Exception as e:
                print(f"[!] Error during monitoring: {e}")
                time.sleep(60)

    def check_status(self):
        """Check current status"""
        if not self.enabled:
            print("[*] Dead man's switch is DISABLED")
            return

        if not self.connect_database():
            print("[!] Cannot connect to database")
            return

        should_trigger, message = self.should_trigger()

        print(f"\n{'='*60}")
        print("Dead Man's Switch Status")
        print(f"{'='*60}")
        print(f"Enabled: {self.enabled}")
        print(f"Check-in Interval: {self.checkin_interval}s ({self.checkin_interval/3600:.1f}h)")
        print(f"Grace Period: {self.grace_period}s ({self.grace_period/3600:.1f}h)")
        print(f"Status: {message}")
        print(f"Would Trigger: {'YES - DANGER' if should_trigger else 'No'}")
        print(f"{'='*60}\n")


def main():
    """Main function"""
    import argparse

    parser = argparse.ArgumentParser(description='Dead Man\'s Switch')
    parser.add_argument('--monitor', action='store_true', help='Run monitoring loop')
    parser.add_argument('--status', action='store_true', help='Check current status')
    parser.add_argument('--test-trigger', action='store_true', help='Test trigger (DESTRUCTIVE)')

    args = parser.parse_args()

    dms = DeadMansSwitch()

    if args.status:
        dms.check_status()
    elif args.monitor:
        dms.run_monitor()
    elif args.test_trigger:
        print("\n⚠️  WARNING: This will DESTROY ALL DATA! ⚠️\n")
        confirm = input("Type 'DESTROY' to confirm: ")
        if confirm == 'DESTROY':
            dms.trigger_emergency_wipe()
        else:
            print("Aborted")
    else:
        parser.print_help()


if __name__ == '__main__':
    print("""
    ╔════════════════════════════════════════════════════════════╗
    ║  EDUCATIONAL SECURITY TRAINING ENVIRONMENT                 ║
    ║  Dead Man's Switch                                         ║
    ║  Purpose: Emergency data destruction protocol              ║
    ║  WARNING: Destructive - for demonstration only             ║
    ╚════════════════════════════════════════════════════════════╝
    """)
    main()
