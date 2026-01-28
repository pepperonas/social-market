#!/usr/bin/env python3
"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Security Monitor
Purpose: Continuous security monitoring and alerting
"""

import os
import sys
import time
import psycopg2
import redis
import requests
from datetime import datetime, timedelta


class SecurityMonitor:
    """
    Security Monitoring Service
    - Service health checks
    - Failed login monitoring
    - Disk usage alerts
    - Tor connectivity
    - Open port scanning
    """

    def __init__(self):
        self.db_conn = None
        self.redis_conn = None
        self.alert_threshold = {
            'failed_logins': 10,
            'disk_usage_percent': 80,
            'service_down_count': 3
        }

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

    def connect_redis(self):
        """Connect to Redis"""
        try:
            self.redis_conn = redis.Redis(
                host=os.environ.get('REDIS_HOST', 'redis'),
                port=os.environ.get('REDIS_PORT', 6379),
                password=os.environ.get('REDIS_PASSWORD', ''),
                decode_responses=True
            )
            self.redis_conn.ping()
            return True
        except Exception as e:
            print(f"[!] Redis connection failed: {e}")
            return False

    def check_service_health(self):
        """Check health of all services"""
        print("[*] Checking service health...")

        services = {
            'PostgreSQL': self.connect_database(),
            'Redis': self.connect_redis(),
            'Nginx': self._check_http('http://nginx:80/health'),
            'Flask App': self._check_http('http://app:5000/health'),
            'Tor': self._check_tor()
        }

        all_healthy = all(services.values())

        print(f"[{'+'  if all_healthy else '!'}] Service Health Check:")
        for service, status in services.items():
            status_str = "UP" if status else "DOWN"
            symbol = "+" if status else "!"
            print(f"    [{symbol}] {service}: {status_str}")

        if not all_healthy:
            self._alert('service_health', f"Services down: {[k for k, v in services.items() if not v]}")

        return all_healthy

    def _check_http(self, url):
        """Check HTTP endpoint"""
        try:
            response = requests.get(url, timeout=5)
            return response.status_code == 200
        except:
            return False

    def _check_tor(self):
        """Check Tor connectivity"""
        try:
            # Simple check if Tor SOCKS port is open
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex(('tor', 9050))
            sock.close()
            return result == 0
        except:
            return False

    def check_failed_logins(self):
        """Check for excessive failed login attempts"""
        print("[*] Checking failed login attempts...")

        if not self.db_conn:
            return

        try:
            cursor = self.db_conn.cursor()

            # Get failed logins in last hour
            cursor.execute("""
                SELECT COUNT(*) FROM auth_log
                WHERE action = 'login_failed'
                AND timestamp > NOW() - INTERVAL '1 hour'
            """)

            count = cursor.fetchone()[0]

            print(f"    Failed logins (last hour): {count}")

            if count > self.alert_threshold['failed_logins']:
                self._alert('failed_logins', f"Excessive failed logins: {count} in last hour")

            cursor.close()
        except Exception as e:
            print(f"[!] Error checking failed logins: {e}")

    def check_disk_usage(self):
        """Check disk usage"""
        print("[*] Checking disk usage...")

        try:
            import shutil
            usage = shutil.disk_usage('/')

            percent_used = (usage.used / usage.total) * 100

            print(f"    Disk usage: {percent_used:.1f}%")

            if percent_used > self.alert_threshold['disk_usage_percent']:
                self._alert('disk_usage', f"High disk usage: {percent_used:.1f}%")

        except Exception as e:
            print(f"[!] Error checking disk usage: {e}")

    def check_security_events(self):
        """Check recent security events"""
        print("[*] Checking security events...")

        if not self.db_conn:
            return

        try:
            cursor = self.db_conn.cursor()

            # Get high-severity events in last hour
            cursor.execute("""
                SELECT event_type, COUNT(*) as count
                FROM security_events
                WHERE severity IN ('critical', 'high')
                AND timestamp > NOW() - INTERVAL '1 hour'
                GROUP BY event_type
            """)

            events = cursor.fetchall()

            if events:
                print("    High-severity events (last hour):")
                for event_type, count in events:
                    print(f"      - {event_type}: {count}")

                self._alert('security_events', f"High-severity events detected: {len(events)}")
            else:
                print("    No high-severity events")

            cursor.close()
        except Exception as e:
            print(f"[!] Error checking security events: {e}")

    def _alert(self, alert_type, message):
        """Send alert (log for now, could send email/webhook)"""
        timestamp = datetime.utcnow().isoformat()
        alert_msg = f"[ALERT] {timestamp} - {alert_type}: {message}"

        print(f"\n{alert_msg}\n")

        # Log to file
        log_file = '/var/log/marketplace/security_alerts.log'
        os.makedirs(os.path.dirname(log_file), exist_ok=True)

        with open(log_file, 'a') as f:
            f.write(f"{alert_msg}\n")

        # Log to database if connected
        if self.db_conn:
            try:
                cursor = self.db_conn.cursor()
                cursor.execute("""
                    INSERT INTO security_events (event_type, severity, source, description)
                    VALUES (%s, %s, %s, %s)
                """, (alert_type, 'high', 'security_monitor', message))
                self.db_conn.commit()
                cursor.close()
            except:
                pass

    def run_monitoring_cycle(self):
        """Run one complete monitoring cycle"""
        print(f"\n{'='*60}")
        print(f"Security Monitoring Cycle - {datetime.utcnow().isoformat()}")
        print(f"{'='*60}\n")

        self.check_service_health()
        self.check_failed_logins()
        self.check_disk_usage()
        self.check_security_events()

        print(f"\n{'='*60}")
        print("Monitoring cycle complete")
        print(f"{'='*60}\n")

    def monitor_continuous(self, interval=300):
        """Run continuous monitoring"""
        print(f"[*] Starting continuous monitoring (interval: {interval}s)")

        while True:
            try:
                self.run_monitoring_cycle()
                time.sleep(interval)
            except KeyboardInterrupt:
                print("\n[*] Monitoring stopped")
                break
            except Exception as e:
                print(f"[!] Error during monitoring: {e}")
                time.sleep(interval)
            finally:
                # Cleanup connections
                if self.db_conn:
                    self.db_conn.close()
                    self.db_conn = None


def main():
    """Main function"""
    import argparse

    parser = argparse.ArgumentParser(description='Security Monitor')
    parser.add_argument('--once', action='store_true',
                       help='Run one monitoring cycle and exit')
    parser.add_argument('--interval', type=int, default=300,
                       help='Monitoring interval in seconds (default: 300)')

    args = parser.parse_args()

    monitor = SecurityMonitor()

    if args.once:
        monitor.run_monitoring_cycle()
    else:
        monitor.monitor_continuous(args.interval)


if __name__ == '__main__':
    print("""
    ╔════════════════════════════════════════════════════════════╗
    ║  EDUCATIONAL SECURITY TRAINING ENVIRONMENT                 ║
    ║  Security Monitor                                          ║
    ║  Purpose: Continuous security monitoring                   ║
    ╚════════════════════════════════════════════════════════════╝
    """)
    main()
