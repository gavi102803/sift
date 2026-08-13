from getpass import getpass
from hashlib import sha256


def main() -> None:
    invite_code = getpass("Invite code: ").strip()
    if not invite_code:
        raise SystemExit("Invite code must not be blank.")
    print(sha256(invite_code.encode()).hexdigest())


if __name__ == "__main__":
    main()
