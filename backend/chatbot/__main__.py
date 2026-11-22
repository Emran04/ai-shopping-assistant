import argparse
from uuid import UUID

from database import create_database_engine
from sqlalchemy.exc import SQLAlchemyError

from chatbot.quota import reset_usage


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage shopping chat usage.")
    commands = parser.add_subparsers(dest="command", required=True)
    reset = commands.add_parser("reset-quota", help="Restore a customer's chat allowance.")
    reset.add_argument("customer_id", type=UUID, help="The customer reference shown in the chat panel.")
    args = parser.parse_args()

    engine = create_database_engine()
    try:
        found = reset_usage(engine, args.customer_id)
    except SQLAlchemyError:
        parser.exit(1, "Could not reset chat usage. Check the database connection and migrations.\n")
    finally:
        engine.dispose()

    if not found:
        parser.exit(1, f"No chat customer found for {args.customer_id}.\n")
    print(f"Reset chat allowance for {args.customer_id}.")


if __name__ == "__main__":
    main()
