#!/usr/bin/python3
import time
import argparse
import re
import json
from mininet.net import Containernet
from mininet.node import Controller
from mininet.cli import CLI
from mininet.link import TCLink
from mininet.log import setLogLevel

setLogLevel('info')

def green(msg):
  print("\033[92m{}\033[0m".format(msg))


def parse_args():
  parser = argparse.ArgumentParser(
      description='Replicated PostgreSQL benchmarking in containernet.')
  parser.add_argument('--replicas', type=int, default=1, required=True, help='Number of replicas (default: 1)')
  parser.add_argument('--delay', type=int, default=0, help='Link delay in ms (default: 0)')
  parser.add_argument('--loss', type=int, default=0, help='Packet loss percentage (default: 0)')
  parser.add_argument('--output', type=str, help="Append benchmark results to this file, e.g. output.jsonl")
  parser.add_argument('--primary-cpu', type=float, default=0.5, help='Primary CPU quota (default: 0.5)')
  parser.add_argument('--replica-cpu', type=float, default=0.5, help='Replica CPU quota (default: 0.5)')
  parser.add_argument('--primary-memory', type=float, default=1000, help='Primary memory quota (in MB, default: 1000)')
  parser.add_argument('--primary-swap-memory', type=float, default=1000, help='Primary swap memory quota (in MB, default: 1000)')
  parser.add_argument('--replica-memory', type=float, default=1000, help='Replica memory quota (in MB, default: 1000)')
  parser.add_argument('--replica-swap-memory', type=float, default=1000, help='Replica swap memory quota (in MB, default: 1000)')

  return parser.parse_args()


def parse_sysbench_output(output):
  """
  Sample output:

    SQL statistics:
        queries performed:
            read:                            840
            write:                           240
            other:                           120
            total:                           1200
        transactions:                        60     (5.96 per sec.)
        queries:                             1200   (119.19 per sec.)
        ignored errors:                      0      (0.00 per sec.)
        reconnects:                          0      (0.00 per sec.)

    General statistics:
        total time:                          10.0662s
        total number of events:              60

    Latency (ms):
            min:                                    5.98
            avg:                                  167.76
            max:                                  845.50
            95th percentile:                      419.45
            sum:                                10065.35

    Threads fairness:
        events (avg/stddev):           60.0000/0.00
        execution time (avg/stddev):   10.0654/0.00
  """

  transactions_per_second_regex = r"transactions:\s+\d+\s+\((.+) per sec\.\)"
  transactions_per_second = re.search(transactions_per_second_regex, output).group(1)

  queries_per_second_regex = r"queries:\s+\d+\s+\((.+) per sec\.\)"
  queries_per_second = re.search(queries_per_second_regex, output).group(1)

  latency_regex = r"Latency \(ms\):\s+min:\s+(.+)\s+avg:\s+(.+)\s+max:\s+(.+)\s+95th percentile:\s+(.+)"
  latency_min, latency_avg, latency_max, latency_95th = re.search(latency_regex, output).groups()

  return {
    'transactions_per_second': float(transactions_per_second),
    'queries_per_second': float(queries_per_second),
    'latency_min': float(latency_min),
    'latency_avg': float(latency_avg),
    'latency_max': float(latency_max),
    'latency_95th': float(latency_95th),
  }


def remove_ansi_escape_sequences(s: str) -> str:
  return re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', s)


def execute_sql(container, sql: str) -> str:
  output = container.cmd(f"PGPASSWORD=postgres psql -U postgres -A -t -X -c \"{sql}\"")
  return remove_ansi_escape_sequences(output).strip();


if __name__ == '__main__':
  args = parse_args()
  net = Containernet(controller=Controller)
  net.addController('c0')

  green('====> Start primary')
  primary = net.addDocker(
      'primary',
      ip='10.1.0.100',
      dcmd="/opt/bitnami/scripts/postgresql/entrypoint.sh /opt/bitnami/scripts/postgresql/run.sh",
      dimage="tip-postgres:latest",
      cpu_period=100000,
      cpu_quota=int(args.primary_cpu * 100000),
      mem_limit=int(args.primary_memory) * 1024 * 1024,
      memswap_limit=int(args.primary_swap_memory) * 1024 * 1024,
      port_bindings={5432: 5432},
      environment={
          "POSTGRESQL_REPLICATION_MODE": "master",
          "POSTGRESQL_REPLICATION_USER": "postgres",
          "POSTGRESQL_REPLICATION_PASSWORD": "postgres",
          "POSTGRESQL_USERNAME": "postgres",
          "POSTGRESQL_PASSWORD": "postgres",
          "POSTGRESQL_DATABASE": "postgres",
          "POSTGRESQL_SYNCHRONOUS_COMMIT_MODE": "remote_apply",
          "POSTGRESQL_NUM_SYNCHRONOUS_REPLICAS": args.replicas,
          "ALLOW_EMPTY_PASSWORD": "yes"
      },
  )

  replicas = []
  for i in range(args.replicas):
      green(f'====> Start replica {i}')
      replicas.append(net.addDocker(
          'replica' + str(i),
          ip='10.1.0.' + str(200 + i),
          dcmd="/opt/bitnami/scripts/postgresql/entrypoint.sh /opt/bitnami/scripts/postgresql/run.sh",
          dimage="tip-postgres:latest",
          cpu_period=100000,
          cpu_quota=int(args.replica_cpu * 100000),
          mem_limit=int(args.replica_memory) * 1024 * 1024,
          memswap_limit=int(args.replica_swap_memory) * 1024 * 1024,
          port_bindings={5432: 5433 + i},
          environment={
              "POSTGRESQL_REPLICATION_MODE": "slave",
              "POSTGRESQL_REPLICATION_USER": "postgres",
              "POSTGRESQL_REPLICATION_PASSWORD": "postgres",
              "POSTGRESQL_MASTER_HOST": "10.1.0.100",
              "POSTGRESQL_PASSWORD": "postgres",
              "POSTGRESQL_MASTER_PORT_NUMBER": "5432",
              "ALLOW_EMPTY_PASSWORD": "yes",
          },
      ))


  green(f'====> Start benchmark container')
  benchmark = net.addDocker(
      'benchmark',
      ip='10.1.0.250',
      dimage="sysbench:latest",
      cpu_period=100000,
      cpu_quota=100000,
  )

  green('====> Setup network')
  s1 = net.addSwitch('s1')
  net.addLink(primary, s1, cls=TCLink, bw=100)

  for replica in replicas:
      net.addLink(replica, s1, cls=TCLink, bw=100, delay=f"{args.delay}ms", loss=args.loss)


  net.addLink(benchmark, s1, cls=TCLink, bw=100)
  net.start()

  green('====> Wait until all replicas are ready')
  for _ in range(20):
    replica_count = execute_sql(primary, "select count(*) from pg_stat_replication where application_name = 'walreceiver' and sync_state = 'sync';")
    print("Ready replicas: ", replica_count)

    if replica_count == str(args.replicas):
      break
    else:
      time.sleep(4)

  green('====> Prepare benchmark')
  print(benchmark.cmd("sysbench --db-driver=pgsql --pgsql-host=10.1.0.100 --pgsql-user=postgres --pgsql-password=postgres --pgsql-db=postgres oltp_read_write prepare"))

  green('====> Run benchmark')
  start = time.time()
  benchmark_output = benchmark.cmd("sysbench --db-driver=pgsql --pgsql-host=10.1.0.100 --pgsql-user=postgres --pgsql-password=postgres --pgsql-db=postgres oltp_read_write run")
  end = time.time()

  # green('====> Start CLI')
  # CLI(net)

  green('====> Teardown')
  net.stop()

  green('====> Results:')
  print(benchmark_output)

  green('Parsed results:')
  results = parse_sysbench_output(benchmark_output)
  print(results)

  run_data = {
    'replicas': args.replicas,
    'delay': args.delay,
    'loss': args.loss,
    'time': end - start,
    'primary_cpu': args.primary_cpu,
    'replica_cpu': args.replica_cpu,
    'primary_memory': args.primary_memory,
    'primary_swap_memory': args.primary_swap_memory,
    'replica_memory': args.replica_memory,
    'replica_swap_memory': args.replica_swap_memory,
  }

  if args.output:
    print("Appending results to file: " + args.output)
    with open(args.output, "a") as outfile:
      outfile.write(json.dumps({**results, **run_data}) + "\n")
