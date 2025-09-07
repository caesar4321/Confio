from django.core.management.base import BaseCommand
from django.db import connection
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Monitor PostgreSQL database connections'
    
    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            # Get connection statistics
            cursor.execute("""
                SELECT 
                    count(*) as total_connections,
                    count(*) FILTER (WHERE state = 'active') as active_connections,
                    count(*) FILTER (WHERE state = 'idle') as idle_connections,
                    count(*) FILTER (WHERE state = 'idle in transaction') as idle_in_transaction,
                    max(now() - query_start) as longest_query_time,
                    (SELECT setting::int FROM pg_settings WHERE name = 'max_connections') as max_connections
                FROM pg_stat_activity;
            """)
            
            result = cursor.fetchone()
            total, active, idle, idle_in_txn, longest_query, max_conns = result
            
            # Calculate percentage usage
            usage_pct = (total / max_conns) * 100
            
            message = (
                f"DB Connection Stats: {total}/{max_conns} ({usage_pct:.1f}%) | "
                f"Active: {active} | Idle: {idle} | Idle in txn: {idle_in_txn} | "
                f"Longest query: {longest_query}"
            )
            
            if usage_pct > 80:
                logger.error(f"HIGH CONNECTION USAGE: {message}")
                self.stdout.write(self.style.ERROR(message))
            elif usage_pct > 60:
                logger.warning(f"ELEVATED CONNECTION USAGE: {message}")
                self.stdout.write(self.style.WARNING(message))
            else:
                logger.info(f"Connection usage normal: {message}")
                self.stdout.write(self.style.SUCCESS(message))
                
            # Get top queries by connection count
            cursor.execute("""
                SELECT 
                    COALESCE(usename, 'system') as username,
                    COALESCE(application_name, 'unknown') as application_name,
                    count(*) as connection_count,
                    string_agg(DISTINCT COALESCE(state, 'unknown'), ', ') as states
                FROM pg_stat_activity 
                GROUP BY usename, application_name
                ORDER BY connection_count DESC
                LIMIT 10;
            """)
            
            self.stdout.write("\nTop connection users:")
            for row in cursor.fetchall():
                username, app_name, conn_count, states = row
                self.stdout.write(f"  {username} ({app_name}): {conn_count} connections ({states})")