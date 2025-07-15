import asyncio
import os
import pickle
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, Optional, Callable, List
import pandas as pd
import numpy as np
from django.utils import timezone
from django.core.cache import cache
from django.conf import settings
from django.db import transaction
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import logging

logger = logging.getLogger(__name__)


class CurtainProgressTracker:
    """Enhanced progress tracker with phase-based reporting"""
    
    def __init__(self, session_id: str, analysis_group_id: int = None):
        self.session_id = session_id
        self.analysis_group_id = analysis_group_id
        self.channel_layer = get_channel_layer()
        self.phases = {
            'initialization': 5,
            'data_download': 40,
            'data_processing': 30,
            'file_creation': 15,
            'database_storage': 10
        }
        self.current_phase = 'initialization'
        self.phase_progress = 0
        self.overall_progress = 0
        self.start_time = timezone.now()
        self.phase_start_time = timezone.now()
        self.estimated_total_time = None
        
    def update_phase_progress(self, phase: str, progress: float, details: Optional[Dict] = None):
        """Update progress for specific phase"""
        if phase in self.phases:
            self.current_phase = phase
            self.phase_progress = progress
            self.phase_start_time = timezone.now()
            
            # Calculate overall progress
            phase_weight = self.phases[phase]
            phase_contribution = (progress / 100) * phase_weight
            
            # Sum up completed phases
            phase_keys = list(self.phases.keys())
            current_phase_index = phase_keys.index(phase)
            completed_phases = phase_keys[:current_phase_index]
            completed_contribution = sum(self.phases[p] for p in completed_phases)
            
            self.overall_progress = completed_contribution + phase_contribution
            
            # Calculate time estimation
            elapsed_time = (timezone.now() - self.start_time).total_seconds()
            if self.overall_progress > 5:  # Need some progress to estimate
                rate = self.overall_progress / elapsed_time
                remaining_progress = 100 - self.overall_progress
                self.estimated_total_time = remaining_progress / rate if rate > 0 else None
            
            # Send enhanced progress message (backward compatible)
            message = {
                "type": "curtain_progress_enhanced",
                "status": "in_progress",
                "overall_progress": round(self.overall_progress, 1),
                "current_phase": phase,
                "phase_progress": progress,
                "details": details or {},
                "timestamp": timezone.now().isoformat(),
                "estimated_remaining_seconds": int(self.estimated_total_time) if self.estimated_total_time else None,
                
                # Backward compatibility fields
                "percentage": round(self.overall_progress, 1),
                "message": f"Phase: {phase.replace('_', ' ').title()} ({progress:.1f}%)"
            }
            
            # Add analysis group ID if available
            if self.analysis_group_id:
                message["analysis_group_id"] = self.analysis_group_id
            
            self.send_progress_message(message)
            
            # Send compose status message for frontend compatibility
            compose_message = {
                "type": "curtain_compose_status",
                "status": "in_progress",
                "percentage": round(self.overall_progress, 1),
                "message": f"Phase: {phase.replace('_', ' ').title()} ({progress:.1f}%)"
            }
            
            # Add analysis group ID if available
            if self.analysis_group_id:
                compose_message["analysis_group_id"] = self.analysis_group_id
                
            self.send_progress_message(compose_message)
            
            # Also send standard progress message for backward compatibility
            if phase == 'data_download':
                standard_message = {
                    "type": "curtain_progress",
                    "status": "downloading",
                    "percentage": progress,
                    "message": f"Downloading data from Curtain ({progress:.1f}%)"
                }
                
                # Add analysis group ID if available
                if self.analysis_group_id:
                    standard_message["analysis_group_id"] = self.analysis_group_id
                    
                self.send_progress_message(standard_message)
    
    def send_progress_message(self, message: Dict):
        """Send progress message via WebSocket"""
        try:
            async_to_sync(self.channel_layer.group_send)(
                f"curtain_{self.session_id}", {
                    "type": "curtain_message",
                    "message": message
                }
            )
        except Exception as e:
            logger.error(f"Failed to send progress message: {e}")
    
    def complete_phase(self, phase: str):
        """Mark a phase as completed"""
        self.update_phase_progress(phase, 100)
        
        # Send phase completion message
        message = {
            "type": "curtain_phase_complete",
            "phase": phase,
            "timestamp": timezone.now().isoformat()
        }
        
        # Add analysis group ID if available
        if self.analysis_group_id:
            message["analysis_group_id"] = self.analysis_group_id
            
        self.send_progress_message(message)


class CurtainCacheManager:
    """Multi-level caching system for Curtain data"""
    
    def __init__(self):
        self.cache_timeout = getattr(settings, 'CURTAIN_CACHE_TIMEOUT', 3600)  # 1 hour
        self.file_cache_dir = os.path.join(settings.MEDIA_ROOT, "curtain_cache")
        os.makedirs(self.file_cache_dir, exist_ok=True)
    
    def get_cache_key(self, link_id: str, data_version: str = "latest") -> str:
        """Generate cache key for link_id"""
        return f"curtain_data:{link_id}:{data_version}"
    
    def get_cached_data(self, link_id: str, data_version: str = "latest") -> Optional[Dict]:
        """Get cached Curtain data if available"""
        cache_key = self.get_cache_key(link_id, data_version)
        
        # Check Django cache first (fast)
        cached_metadata = cache.get(cache_key)
        if cached_metadata:
            file_path = cached_metadata.get('file_path')
            if file_path and os.path.exists(file_path):
                try:
                    with open(file_path, 'rb') as f:
                        return pickle.load(f)
                except Exception as e:
                    logger.warning(f"Failed to load cached file {file_path}: {e}")
                    # Remove invalid cache entry
                    cache.delete(cache_key)
                    if os.path.exists(file_path):
                        os.remove(file_path)
        
        return None
    
    def cache_data(self, link_id: str, data: Dict, data_version: str = "latest") -> bool:
        """Cache Curtain data with TTL and timestamp"""
        try:
            cache_key = self.get_cache_key(link_id, data_version)
            
            # Add timestamp to data for freshness tracking
            data_with_timestamp = {
                **data,
                'timestamp': timezone.now().isoformat()
            }
            
            # Create file cache
            file_path = os.path.join(self.file_cache_dir, f"{link_id}_{data_version}_{int(time.time())}.pkl")
            with open(file_path, 'wb') as f:
                pickle.dump(data_with_timestamp, f)
            
            # Store metadata in Django cache
            cache.set(cache_key, {
                'file_path': file_path,
                'created_at': timezone.now().isoformat(),
                'data_size': len(str(data))
            }, timeout=self.cache_timeout)
            
            return True
        except Exception as e:
            logger.error(f"Failed to cache data for {link_id}: {e}")
            return False
    
    def invalidate_cache(self, link_id: str):
        """Invalidate cache for specific link"""
        # Remove from Django cache
        cache_pattern = f"curtain_data:{link_id}:*"
        
        # Django cache doesn't support pattern deletion directly
        # So we'll use a more targeted approach
        for version in ["latest", "v1", "v2"]:  # Common versions
            cache_key = self.get_cache_key(link_id, version)
            cached_data = cache.get(cache_key)
            if cached_data:
                file_path = cached_data.get('file_path')
                if file_path and os.path.exists(file_path):
                    os.remove(file_path)
                cache.delete(cache_key)
    
    def cleanup_old_cache(self, max_age_hours: int = 24):
        """Clean up old cache files"""
        try:
            cutoff_time = time.time() - (max_age_hours * 3600)
            for filename in os.listdir(self.file_cache_dir):
                if filename.endswith('.pkl'):
                    file_path = os.path.join(self.file_cache_dir, filename)
                    if os.path.getmtime(file_path) < cutoff_time:
                        os.remove(file_path)
        except Exception as e:
            logger.error(f"Failed to cleanup cache: {e}")


class CurtainErrorHandler:
    """Comprehensive error handling with automatic recovery"""
    
    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries
        self.retry_delays = [1, 2, 4, 8, 16]  # Exponential backoff
    
    def handle_with_retry(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function with comprehensive error handling"""
        last_exception = None
        
        for attempt in range(self.max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                
                if attempt < self.max_retries - 1:
                    delay = self.retry_delays[min(attempt, len(self.retry_delays) - 1)]
                    logger.warning(f"Attempt {attempt + 1} failed, retrying in {delay}s: {e}")
                    time.sleep(delay)
                else:
                    logger.error(f"All {self.max_retries} attempts failed: {e}")
        
        # If we get here, all attempts failed
        raise last_exception
    
    def handle_partial_failure(self, session_id: str, successful_operations: List[str], failed_operations: Dict[str, str]):
        """Handle partial failures gracefully"""
        if successful_operations:
            try:
                channel_layer = get_channel_layer()
                message = {
                    "type": "curtain_partial_success",
                    "status": "partial_success",
                    "successful_operations": successful_operations,
                    "failed_operations": failed_operations,
                    "message": f"Import partially completed. {len(successful_operations)} operations succeeded, {len(failed_operations)} failed."
                }
                
                async_to_sync(channel_layer.group_send)(
                    f"curtain_{session_id}", {
                        "type": "curtain_message",
                        "message": message
                    }
                )
            except Exception as e:
                logger.error(f"Failed to send partial failure message: {e}")
        
        # Log detailed failure information
        for operation, error in failed_operations.items():
            logger.error(f"Failed operation {operation}: {error}")


class EnhancedCurtainProcessor:
    """Enhanced processor for Curtain datasets with caching, parallel processing, and better error handling"""
    
    def __init__(self, parallel_workers: int = 3):
        self.parallel_workers = parallel_workers
        self.cache_manager = CurtainCacheManager()
        self.error_handler = CurtainErrorHandler()
        self.executor = ThreadPoolExecutor(max_workers=parallel_workers)
    
    def process_curtain_data_enhanced(self, curtain_client, link_id: str, session_id: str, analysis_group_id: int = None) -> Dict:
        """Process Curtain datasets with caching, enhanced progress tracking, and better error handling"""
        progress_tracker = CurtainProgressTracker(session_id, analysis_group_id)
        
        try:
            # Don't send started message - let RQ task handle it to avoid duplication
            
            # Phase 1: Initialization
            progress_tracker.update_phase_progress('initialization', 0, {'step': 'Starting initialization'})
            
            # Check cache first
            cached_data = self.cache_manager.get_cached_data(link_id)
            if cached_data:
                progress_tracker.update_phase_progress('initialization', 100, {'step': 'Using cached data'})
                progress_tracker.complete_phase('initialization')

                return cached_data
            
            progress_tracker.update_phase_progress('initialization', 50, {'step': 'Preparing download'})
            
            # Phase 2: Data Download with progress callback
            progress_tracker.update_phase_progress('data_download', 0, {'step': 'Starting download'})
            
            def download_progress_callback(downloaded_bytes: int, total_bytes: int, percentage: float):
                progress_tracker.update_phase_progress('data_download', percentage, {
                    'downloaded_bytes': downloaded_bytes,
                    'total_bytes': total_bytes,
                    'step': 'Downloading data'
                })
            
            # Download data with progress tracking and retry logic
            curtain_data = self.error_handler.handle_with_retry(
                curtain_client.download_curtain_session,
                link_id,
                retries=2,
                progress_callback=download_progress_callback
            )
            
            if not curtain_data:
                raise Exception("Failed to download Curtain data")
            
            progress_tracker.complete_phase('data_download')
            
            # Phase 3: Data Processing (no actual chunking since curtain client doesn't support it)
            progress_tracker.update_phase_progress('data_processing', 0, {'step': 'Starting processing'})
            
            # Just return the data as-is since we can't actually stream it
            processed_data = curtain_data
            
            progress_tracker.update_phase_progress('data_processing', 100, {'step': 'Processing complete'})
            progress_tracker.complete_phase('data_processing')
            
            # Cache the processed data
            try:
                self.cache_manager.cache_data(link_id, processed_data)
            except Exception as e:
                logger.warning(f"Failed to cache data: {e}")
            
            # Don't send completion message - let RQ task handle it to avoid duplication
            return processed_data
            
        except Exception as e:
            logger.error(f"Enhanced processing failed: {e}")
            # Send error message for compatibility
            try:
                progress_tracker.send_progress_message({
                    "type": "curtain_compose_status",
                    "status": "error",
                    "error": str(e),
                    "message": "Failed to process Curtain data"
                })
            except Exception as msg_error:
                logger.error(f"Failed to send error message: {msg_error}")
            raise
    
    def process_parallel_data_types(self, curtain_data: Dict, analysis_group, session_id: str) -> Dict:
        """Process different data types in parallel"""
        progress_tracker = CurtainProgressTracker(session_id, analysis_group.id)
        
        # Define processing tasks
        tasks = [
            ('differential_data', self._process_differential_data),
            ('searched_data', self._process_searched_data),
            ('annotations', self._process_annotations),
            ('uniprot_enrichment', self._process_uniprot_enrichment)
        ]
        
        # Submit tasks to executor
        future_to_task = {
            self.executor.submit(task_func, curtain_data, analysis_group, session_id): task_name
            for task_name, task_func in tasks
        }
        
        results = {}
        successful_operations = []
        failed_operations = {}
        
        for future in as_completed(future_to_task):
            task_name = future_to_task[future]
            try:
                result = future.result()
                results[task_name] = result
                successful_operations.append(task_name)
                
                # Send progress update
                progress = (len(results) / len(tasks)) * 100
                progress_tracker.update_phase_progress('data_processing', progress, {
                    'completed_task': task_name,
                    'total_tasks': len(tasks)
                })
                
            except Exception as e:
                logger.error(f"Error processing {task_name}: {e}")
                failed_operations[task_name] = str(e)
                results[task_name] = None
        
        # Handle partial failures
        if failed_operations:
            self.error_handler.handle_partial_failure(session_id, successful_operations, failed_operations)
        
        return results
    
    def _process_differential_data(self, curtain_data: Dict, analysis_group, session_id: str) -> str:
        """Process differential analysis data"""
        return curtain_data.get('processed', '')
    
    def _process_searched_data(self, curtain_data: Dict, analysis_group, session_id: str) -> str:
        """Process raw searched data"""
        return curtain_data.get('raw', '')
    
    def _process_annotations(self, curtain_data: Dict, analysis_group, session_id: str) -> Dict:
        """Process annotations data"""
        return curtain_data.get('settings', {})
    
    def _process_uniprot_enrichment(self, curtain_data: Dict, analysis_group, session_id: str) -> Dict:
        """Process UniProt enrichment data"""
        return curtain_data.get('extraData', {}).get('uniprot', {})
    
    def __del__(self):
        """Cleanup executor on deletion"""
        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=True)


class CurtainDataValidator:
    """Data validation and integrity checks"""
    
    def __init__(self):
        self.required_fields = {
            'differential': ['Primary ID', 'Fold Change', 'P-value'],
            'searched': ['Primary ID'],
            'settings': ['differentialForm', 'rawForm']
        }
    
    def validate_curtain_data(self, curtain_data: Dict) -> Dict[str, Any]:
        """Validate downloaded Curtain data"""
        validation_results = {
            'is_valid': True,
            'errors': [],
            'warnings': []
        }
        
        # Check required sections
        for section in ['processed', 'raw', 'settings']:
            if section not in curtain_data:
                validation_results['errors'].append(f"Missing required section: {section}")
                validation_results['is_valid'] = False
        
        # Validate data format
        if 'processed' in curtain_data:
            diff_validation = self._validate_differential_data(curtain_data['processed'])
            validation_results['errors'].extend(diff_validation['errors'])
            validation_results['warnings'].extend(diff_validation['warnings'])
        
        # Validate settings
        if 'settings' in curtain_data:
            settings_validation = self._validate_settings(curtain_data['settings'])
            validation_results['errors'].extend(settings_validation['errors'])
            validation_results['warnings'].extend(settings_validation['warnings'])
        
        return validation_results
    
    def _validate_differential_data(self, processed_data: str) -> Dict[str, List[str]]:
        """Validate differential analysis data"""
        validation_results = {'errors': [], 'warnings': []}
        
        try:
            # Try to parse as CSV
            import io
            df = pd.read_csv(io.StringIO(processed_data))
            
            # Check required columns
            required_cols = self.required_fields['differential']
            missing_cols = [col for col in required_cols if col not in df.columns]
            
            if missing_cols:
                validation_results['errors'].append(f"Missing required columns: {missing_cols}")
            
            # Check data types
            if 'Fold Change' in df.columns:
                if not pd.api.types.is_numeric_dtype(df['Fold Change']):
                    validation_results['warnings'].append("Fold Change column is not numeric")
            
            # Check for empty data
            if df.empty:
                validation_results['errors'].append("Differential data is empty")
            
        except Exception as e:
            validation_results['errors'].append(f"Could not parse differential data: {e}")
        
        return validation_results
    
    def _validate_settings(self, settings_data) -> Dict[str, List[str]]:
        """Validate settings data"""
        validation_results = {'errors': [], 'warnings': []}
        
        try:
            if isinstance(settings_data, str):
                import json
                settings_data = json.loads(settings_data)
            
            required_settings = self.required_fields['settings']
            missing_settings = [setting for setting in required_settings if setting not in settings_data]
            
            if missing_settings:
                validation_results['errors'].append(f"Missing required settings: {missing_settings}")
            
        except Exception as e:
            validation_results['errors'].append(f"Could not parse settings data: {e}")
        
        return validation_results