#!/bin/bash
set -e

for replicas in 1 2 3 4; do
  echo "======> Replicas: $replicas"
  sudo ./benchmark.py \
    --replicas $replicas \
    --delay 0 \
    --output replicas.jsonl
done

for delay in 5 10 15 20 25 30 35 40 45 50; do
  for replicas in 1 2; do
    echo "======> Delay: $delay, Replicas: $replicas"
    sudo ./benchmark.py \
      --replicas $replicas \
      --delay $delay \
      --output delay.jsonl
  done
done

for primary_cpu in 0.1 0.2 0.3 0.4 0.5; do
  echo "======> Primary CPU: $primary_cpu"
  sudo ./benchmark.py \
    --replicas 1 \
    --primary-cpu $primary_cpu \
    --output primary_cpu.jsonl
done

for replica_cpu in 0.1 0.2 0.3 0.4 0.5; do
  echo "======> Replica CPU: $replica_cpu"
  sudo ./benchmark.py \
    --replicas 1 \
    --replica-cpu $replica_cpu \
    --output replica_cpu.jsonl
done

