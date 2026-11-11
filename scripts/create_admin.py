#!/usr/bin/env python3
"""Create one local super-admin without embedding credentials in source code."""

import argparse
import getpass
import os
import sys
from uuid import uuid4

import bcrypt
import psycopg2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
        help="Database URL; defaults to DATABASE_URL",
    )
    args = parser.parse_args()

    if not args.database_url:
        parser.error("set DATABASE_URL or pass --database-url")

    password = getpass.getpass("New administrator password: ")
    confirmation = getpass.getpass("Repeat administrator password: ")
    if password != confirmation:
        print("Passwords do not match.", file=sys.stderr)
        return 2
    if len(password) < 12:
        print("Use at least 12 characters.", file=sys.stderr)
        return 2

    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")
    with psycopg2.connect(args.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM users WHERE email = %s", (args.email,))
            if cur.fetchone():
                print("An account with this email already exists.", file=sys.stderr)
                return 2
            cur.execute(
                """
                INSERT INTO users (id, tenant_id, email, password_hash, full_name, role, is_active, email_verified)
                VALUES (%s, NULL, %s, %s, %s, 'super_admin', TRUE, TRUE)
                """,
                (str(uuid4()), args.email, password_hash, args.name),
            )
    print(f"Created local super-admin account for {args.email}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
