#!/usr/bin/env python3

"""
Migrate (install or update) database schema
"""

import argparse

from mediawords.db import connect_to_db
from mediawords.db.schema.migrate import migration_sql
from mediawords.util.log import create_logger

log = create_logger(__name__)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Migrate database schema.")
    parser.add_argument('-d', '--dryrun', action='store_true',
                        help="Print what is about to be executed instead of executing it")
    args = parser.parse_args()

    db_ = connect_to_db()

    db_.begin()

    sql = migration_sql(db_)

    if sql:
        if args.dryrun:
            log.info("Printing migration SQL...")
            print(sql)
            log.info("Done printing migration SQL.")
        else:
            log.info("Executing migration SQL...")
            db_.query(sql)
            log.info("Done executing migration SQL.")

    else:
        log.info("Schema is up-to-date, nothing to do.")

    db_.commit()
