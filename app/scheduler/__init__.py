"""
IronkeepV2 scheduler package.

Entry point: python -m app.scheduler
Requires: SCHEDULER_ENABLED=1

Job functions in app.scheduler.jobs are plain callables — they can be
imported and called directly in tests without starting the polling loop.
"""
