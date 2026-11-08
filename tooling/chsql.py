import os
import sys
from dotenv import load_dotenv
import clickhouse_connect

load_dotenv()

client = clickhouse_connect.get_client(
    host=os.getenv("CLICKHOUSE_HOST", "clickhouse.dronenav.org"),
    port=int(os.getenv("CLICKHOUSE_PORT", "8123")),
    username=os.getenv("CLICKHOUSE_USER", "dronenav"),
    password=os.environ["CLICKHOUSE_PASSWORD"],
    database=os.getenv("CLICKHOUSE_DATABASE", "dronenav"),
)


def main():
    if len(sys.argv) < 2:
        print('Usage: python -m app.navproxy.tooling.chsql "SQL"')
        sys.exit(1)

    sql = " ".join(sys.argv[1:])

    result = client.query(sql)

    if result.column_names:
        print("\t".join(result.column_names))

    for row in result.result_rows:
        print("\t".join(str(value) for value in row))


if __name__ == "__main__":
    main()

