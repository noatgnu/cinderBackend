import os
import time
from django.core.management.base import BaseCommand
from django.conf import settings
from cb.curtain.enhanced_processor import CurtainCacheManager


class Command(BaseCommand):
    help = 'Clean up old Curtain cache files'

    def add_arguments(self, parser):
        parser.add_argument(
            '--max-age-hours',
            type=int,
            default=24,
            help='Maximum age in hours for cache files (default: 24)'
        )

    def handle(self, *args, **options):
        max_age_hours = options['max_age_hours']
        
        self.stdout.write(f'Cleaning up Curtain cache files older than {max_age_hours} hours...')
        
        cache_manager = CurtainCacheManager()
        
        try:
            cache_manager.cleanup_old_cache(max_age_hours)
            self.stdout.write(
                self.style.SUCCESS(f'Successfully cleaned up cache files older than {max_age_hours} hours')
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error cleaning up cache: {e}')
            )