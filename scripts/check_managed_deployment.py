#!/usr/bin/env python3
from sift_backend.config import load_settings, managed_deployment_errors


def main() -> int:
    errors = managed_deployment_errors(load_settings())
    if errors:
        print("Managed deployment configuration is not ready:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Managed deployment configuration is ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
