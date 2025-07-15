"""
Curtain enhanced processing settings configuration.
Add these to your Django settings.py file:

# Curtain Cache Settings
CURTAIN_CACHE_TIMEOUT = 3600  # 1 hour in seconds
CURTAIN_CACHE_CLEANUP_HOURS = 24  # Clean up files older than 24 hours
CURTAIN_PARALLEL_WORKERS = 3  # Number of parallel workers for processing
CURTAIN_RETRY_ATTEMPTS = 3  # Number of retry attempts for failed operations
CURTAIN_ENABLE_CACHING = True  # Enable/disable caching
CURTAIN_ENABLE_ENHANCED = True  # Enable/disable enhanced processing
CURTAIN_ENABLE_PARALLEL = True  # Enable/disable parallel processing

# Logging configuration for Curtain processing
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'curtain_file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': '/path/to/curtain.log',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'cb.curtain': {
            'handlers': ['curtain_file'],
            'level': 'INFO',
            'propagate': True,
        },
    },
}
"""

# Default values that can be overridden in settings.py
DEFAULT_CURTAIN_SETTINGS = {
    'CURTAIN_CACHE_TIMEOUT': 3600,
    'CURTAIN_CACHE_CLEANUP_HOURS': 24,
    'CURTAIN_PARALLEL_WORKERS': 3,
    'CURTAIN_RETRY_ATTEMPTS': 3,
    'CURTAIN_ENABLE_CACHING': True,
    'CURTAIN_ENABLE_ENHANCED': True,
    'CURTAIN_ENABLE_PARALLEL': True,
}