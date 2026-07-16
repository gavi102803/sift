#!/usr/bin/env python3
import argparse
from datetime import UTC, datetime

from sift_backend.config import load_settings
from sift_backend.identity_access.persistence import SqlAlchemyBetaAuthRepository
from sift_backend.persistence.database import create_session_factory


def main() -> int:
    parser = argparse.ArgumentParser(description="Revoke every beta session for one owner.")
    parser.add_argument("owner_id")
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    if not args.confirm:
        parser.error("--confirm is required")

    settings = load_settings()
    repository = SqlAlchemyBetaAuthRepository(
        create_session_factory(settings.database_url, initialize_schema=False)
    )
    repository.revoke_owner(args.owner_id, datetime.now(UTC))
    print(f"Revoked beta access for owner {args.owner_id}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
