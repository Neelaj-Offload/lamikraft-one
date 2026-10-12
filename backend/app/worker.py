"""Worker entrypoint: ``uv run python -m app.worker``."""

from app.platform.jobs.worker import main

if __name__ == "__main__":
    main()
