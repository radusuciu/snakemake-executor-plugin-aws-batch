# Snakemake executor plugin: aws-batch

A Snakemake executor plugin for submitting jobs to AWS Batch. Full documentation can be found in the [Snakemake plugin catalog](https://snakemake.github.io/snakemake-plugin-catalog/plugins/executor/aws-batch.html).

## Configuration Reference

### Executor Settings

| Setting | CLI Flag | Environment Variable | Description |
|---------|----------|---------------------|-------------|
| Region | `--aws-batch-region` | `SNAKEMAKE_AWS_BATCH_REGION` | AWS region |
| Job Queue | `--aws-batch-job-queue` | `SNAKEMAKE_AWS_BATCH_JOB_QUEUE` | Default job queue ARN |
| Job Role | `--aws-batch-job-role` | `SNAKEMAKE_AWS_BATCH_JOB_ROLE` | IAM role for job execution |
| Execution Role | `--aws-batch-execution-role` | `SNAKEMAKE_AWS_BATCH_EXECUTION_ROLE` | IAM role for ECS agent (required for secrets) |
| Global Secrets | `--aws-batch-secrets` | `SNAKEMAKE_AWS_BATCH_SECRETS` | Global secrets (JSON string) |
| Task Timeout | `--aws-batch-task-timeout` | - | Default job timeout in seconds (default: 300) |

### Per-Rule Resource Configurations

| Resource | Type | Description |
|----------|------|-------------|
| `aws_batch_vcpu` | integer | Number of vCPUs (default: 1) |
| `aws_batch_mem_mb` | integer | Memory in MiB (default: 1024) |
| `aws_batch_gpu` | integer | Number of GPUs (default: 0) |
| `aws_batch_job_queue` | string | Override default job queue for specific rule |
| `aws_batch_container_image` | string | Use custom container image for rule |
| `aws_batch_secrets` | JSON string | Rule-specific secrets. Format: `'[{"name":"MY_SECRET","valueFrom":"arn:aws:secretsmanager:..."}]'` |
| `aws_batch_consumable_resources` | JSON string | Consumable resources (e.g., licenses). Format: `'[{"consumableResource":"name","quantity":N}]'` |
| `aws_batch_timeout` | integer | Rule-specific timeout in seconds (min: 60) |
| `aws_batch_retry_strategy` | JSON string | Retry strategy configuration. Format: `'{"attempts":N,"evaluateOnExit":[...]}'` |
| `aws_batch_job_name_suffix` | string | Custom suffix for job names |
| `aws_batch_job_uuid` | string | Custom identifier/UUID for job names (default: auto-generated UUID) |
