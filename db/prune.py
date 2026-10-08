from __future__ import annotations

import sys

from common.config import load_config
from common.database import connect
from db.partitions import prune_old_partitions


def main() -> None:
    if "--yes" not in sys.argv:
        sys.exit("Refusing to drop partitions without --yes")
    conn = connect(test="--test" in sys.argv)
    dropped = prune_old_partitions(conn, load_config().retention_months)
    print("dropped:", ", ".join(dropped) if dropped else "nothing to drop")


if __name__ == "__main__":
    main()
