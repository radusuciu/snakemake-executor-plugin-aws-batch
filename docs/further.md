# AWS Credentials

This plugin assumes you have setup AWS CLI credentials in ~/.aws/credentials. For more
information see [aws cli configuration](https://docs.aws.amazon.com/cli/v1/userguide/cli-configure-files.html).

# AWS Infrastructure Requirements

The snakemake-executor-plugin-aws-batch requires an EC2 compute environment and a job queue
to be configured. The plugin repo [contains terraform](https://github.com/snakemake/snakemake-executor-plugin-aws-batch/tree/main/terraform) used to setup
the requisite AWS Batch infrastructure.

# Compute Resources

You can specify compute requirements for each rule using these resource parameters:

## vCPU, Memory, and GPU

```python
rule compute_intensive:
    input:
        "input.txt"
    output:
        "output.txt"
    resources:
        aws_batch_vcpu=4,        # Number of vCPUs (default: 1)
        aws_batch_mem_mb=8192,   # Memory in MiB (default: 1024)
        aws_batch_gpu=1          # Number of GPUs (default: 0)
    shell:
        "process.sh {input} {output}"
```

**Note:** For Fargate compute environments, vCPU and memory must conform to valid combinations as specified in the [AWS Batch Fargate documentation](https://docs.aws.amazon.com/batch/latest/userguide/fargate.html). The plugin will validate these combinations and automatically adjust memory to the minimum allowed value if an invalid combination is specified.

For EC2 compute environments, any positive vCPU and memory values are allowed (minimum 1 vCPU and 1024 MiB).

# Per-Rule Configuration

You can override the default job queue for specific rules using the `aws_batch_job_queue` resource:

```python
rule special_task:
    output:
        "output.txt"
    resources:
        aws_batch_job_queue="arn:aws:batch:us-west-2:123456789012:job-queue/special-queue"
    shell:
        "echo 'task' > {output}"
```

Assuming you have [terraform](https://developer.hashicorp.com/terraform/install) 
installed and aws cli credentials configured, you can deploy
the required infrastructure as follows: 

```
cd terraform
terraform init
terraform plan
terraform apply
```

Resource names can be updated by including a terraform.tfvars file that specifies 
variable name overrides of the defaults defined in vars.tf. The outputs variables from  
running terraform apply can be exported as environment variables for snakemake-executor-plugin-aws-batch to use.

SNAKEMAKE_AWS_BATCH_REGION
SNAKEMAKE_AWS_BATCH_JOB_QUEUE
SNAKEMAKE_AWS_BATCH_JOB_ROLE
SNAKEMAKE_AWS_BATCH_EXECUTION_ROLE


# AWS Secrets

This plugin supports injecting secrets from AWS Secrets Manager or AWS Systems Manager Parameter Store into your Batch jobs. Secrets can be configured globally (applied to all jobs) or per-rule (applied to specific rules).

## Global Secrets

Global secrets are configured via the `--aws-batch-secrets` CLI flag or the `SNAKEMAKE_AWS_BATCH_SECRETS` environment variable, and are applied to all jobs. **Note:** Using secrets requires an execution role to be specified via `--aws-batch-execution-role`.

```bash
snakemake --executor aws-batch \
    --aws-batch-execution-role arn:aws:iam::123456789:role/ecsTaskExecutionRole \
    --aws-batch-secrets '[{"name":"DB_PASSWORD","valueFrom":"arn:aws:secretsmanager:us-west-2:123456789:secret:db-pass"}]'
```

## Per-Rule Secrets

Per-rule secrets are specified in the Snakefile using the `aws_batch_secrets` resource. The value must be a **JSON string** (not a Python list):

```python
rule my_rule:
    input: "input.txt"
    output: "output.txt"
    resources:
        aws_batch_secrets='[{"name":"API_KEY","valueFrom":"arn:aws:secretsmanager:us-west-2:123456789:secret:api-key"}]'
    shell:
        "process_data.sh {input} {output}"
```

## Merging Global and Per-Rule Secrets

When both global and per-rule secrets are specified, they are merged. If a secret with the same `name` is defined in both global and per-rule secrets, the per-rule value takes precedence.

## Secret Format

Secrets must be formatted as a JSON array of objects, where each object has two keys:
- `name`: The name of the environment variable to set in the container
- `valueFrom`: The ARN of the secret in AWS Secrets Manager or Systems Manager Parameter Store

**Note:** When using global secrets (via `--aws-batch-secrets`), the value is passed as a JSON string on the command line. When using per-rule secrets (via `aws_batch_secrets` resource), the value must also be a JSON string within the Snakefile.

**Secrets Manager example:**
```
arn:aws:secretsmanager:region:account-id:secret:secret-name
```

**Systems Manager Parameter Store example:**
```
arn:aws:ssm:region:account-id:parameter/parameter-name
```

## Required IAM Permissions

### Understanding Job Role vs Execution Role

AWS Batch uses two different IAM roles with distinct purposes:

- **Execution Role** (`--aws-batch-execution-role`): Used by the AWS ECS agent to pull container images, fetch secrets from AWS Secrets Manager/Systems Manager, and send logs to CloudWatch. This role is required when using secrets.

- **Job Role** (`--aws-batch-job-role`): Used by the containerized application to access AWS services (e.g., S3, DynamoDB) during job execution.

### Execution Role Permissions (Required for Secrets)

When using secrets, you must provide an execution role with permissions to access AWS Secrets Manager or Systems Manager Parameter Store:

```bash
snakemake --executor aws-batch \
    --aws-batch-execution-role arn:aws:iam::123456789:role/ecsTaskExecutionRole \
    --aws-batch-secrets '[{"name":"DB_PASSWORD","valueFrom":"arn:aws:secretsmanager:..."}]'
```

The execution role must have the following permissions:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "secretsmanager:GetSecretValue",
                "ssm:GetParameters"
            ],
            "Resource": [
                "arn:aws:secretsmanager:region:account-id:secret:*",
                "arn:aws:ssm:region:account-id:parameter/*"
            ]
        }
    ]
}
```

Additionally, the execution role should include the AWS managed policy `AmazonECSTaskExecutionRolePolicy` for basic ECS task execution permissions (CloudWatch Logs, ECR access).

# Rule-Specific Container Images

By default, all jobs use the global container image specified via `--container-image`. However, you can specify a different container image for individual rules using the `aws_batch_container_image` resource parameter:

```python
rule my_rule:
    input:
        "input.txt"
    output:
        "output.txt"
    resources:
        aws_batch_container_image="my-custom-image:tag"
    shell:
        "process_data.sh {input} {output}"
```

This allows you to use different containers with specialized tools for different rules within the same workflow, rather than requiring all tools to be present in a single container.

# Consumable Resources

AWS Batch supports [consumable resources](https://docs.aws.amazon.com/batch/latest/userguide/resource-aware-scheduling-how-to-create.html) for rate-limited resources like software licenses, database connections, or API tokens. Consumable resources enable resource-aware scheduling, ensuring jobs only run when the required resources are available.

## Creating Consumable Resources

Before using consumable resources in your workflows, you must create them in AWS Batch. Each consumable resource requires:
- **Resource Name**: Unique identifier for the resource
- **Total Quantity**: Maximum number of units available
- **Resource Type**: Either `REPLENISHABLE` (resources return to pool after job completes) or `NON_REPLENISHABLE` (resources are permanently consumed)

Create a consumable resource using the AWS CLI:

```bash
aws batch create-consumable-resource \
    --consumable-resource-name license-pool \
    --total-quantity 10 \
    --resource-type REPLENISHABLE
```

## Using Consumable Resources in Rules

Specify consumable resources at the rule level using the `aws_batch_consumable_resources` resource parameter. The value must be a **JSON string** (not a Python list) containing an array of objects, each with:
- `consumableResource`: The name of the consumable resource
- `quantity`: The number of units required (must be a positive integer)

```python
rule licensed_analysis:
    input:
        "data.txt"
    output:
        "analysis.txt"
    resources:
        aws_batch_consumable_resources='[{"consumableResource": "license-pool", "quantity": 2}]'
    shell:
        "run_analysis.sh {input} {output}"
```

**Note:** Like `aws_batch_secrets`, the value must be a JSON string within the Snakefile because Snakemake resources can only be strings, integers, or callables returning those types.

# Rule-Specific Job Timeouts

By default, all jobs use the global timeout specified via `--aws-batch-task-timeout` (default: 300 seconds). However, you can specify a different timeout for individual rules using the `aws_batch_timeout` resource parameter:

```python
rule long_running_task:
    input:
        "input.txt"
    output:
        "output.txt"
    resources:
        aws_batch_timeout=7200  # 2 hours
    shell:
        "long_process.sh {input} {output}"
```

The timeout value must be:
- An integer representing seconds
- At least 60 seconds (AWS Batch minimum)
- No maximum limit (though Fargate jobs have a practical 14-day limit)

Per-rule timeouts take precedence over the global `--aws-batch-task-timeout` setting, allowing you to customize timeouts for specific rules that need more (or less) time to complete.

# Custom Job Name Suffixes

By default, AWS Batch jobs are named using the pattern `snakejob-{rule_name}-{uuid}`. You can add a custom suffix to job names for better identification and organization using the `aws_batch_job_name_suffix` resource parameter:

```python
rule my_analysis:
    input:
        "input.txt"
    output:
        "output.txt"
    resources:
        aws_batch_job_name_suffix="experiment-v2"
    shell:
        "process_data.sh {input} {output}"
```

This will produce job names in the format:
```
snakejob-my_analysis-experiment-v2-a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

Without the custom suffix, the default naming pattern is used:
```
snakejob-my_analysis-a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

# Custom Job Identifiers

By default, AWS Batch job names include an automatically generated UUID for uniqueness. You can override this with a custom identifier using the `aws_batch_job_uuid` resource parameter:

```python
rule my_analysis:
    input:
        "input.txt"
    output:
        "output.txt"
    resources:
        aws_batch_job_uuid="custom-id-12345"
    shell:
        "process_data.sh {input} {output}"
```

This will produce job names in the format:
```
snakejob-my_analysis-custom-id-12345
```

You can combine both custom suffix and custom UUID:

```python
rule my_analysis:
    input:
        "input.txt"
    output:
        "output.txt"
    resources:
        aws_batch_job_name_suffix="experiment-v2",
        aws_batch_job_uuid="run-001"
    shell:
        "process_data.sh {input} {output}"
```

This will produce job names in the format:
```
snakejob-my_analysis-experiment-v2-run-001
```

# Retry Strategies

AWS Batch supports automatic retry of failed jobs using retry strategies. Retry strategies allow you to configure how many times a job should be retried and under what conditions retries should occur. This is useful for handling transient failures like temporary network issues, spot instance interruptions, or resource constraints.

## Basic Retry Strategy

The simplest retry strategy specifies just the number of retry attempts (1-10):

```python
import json

rule flaky_task:
    input:
        "input.txt"
    output:
        "output.txt"
    resources:
        aws_batch_retry_strategy=json.dumps({
            "attempts": 3
        })
    shell:
        "process.sh {input} {output}"
```

## Advanced Retry with Conditional Logic

For more control, you can use `evaluateOnExit` to specify conditions that determine whether a job should be retried or exit based on exit codes, status reasons, or custom reason strings:

```python
import json

rule conditional_retry:
    input:
        "input.txt"
    output:
        "output.txt"
    resources:
        aws_batch_retry_strategy=json.dumps({
            "attempts": 5,
            "evaluateOnExit": [
                {
                    "action": "RETRY",
                    "onExitCode": "137"  # OOM killer
                },
                {
                    "action": "RETRY",
                    "onStatusReason": "Host EC2*"  # EC2 spot interruption
                },
                {
                    "action": "RETRY",
                    "onReason": "*timeout*"  # Timeout errors
                },
                {
                    "action": "EXIT",
                    "onExitCode": "0"  # Success - don't retry
                }
            ]
        })
    shell:
        "process.sh {input} {output}"
```

## Retry Strategy Configuration

The retry strategy is specified as a **JSON string** using the `aws_batch_retry_strategy` resource parameter. It supports the following fields:

### `attempts` (integer, optional)
- Number of times to retry a failed job
- Must be between 1 and 10
- If not specified, AWS Batch uses its default retry behavior

### `evaluateOnExit` (array, optional)
- Array of up to 5 evaluation rules that determine whether to retry or exit
- Each rule is evaluated in order until a match is found
- If none of the conditions match, the job is retried

Each `evaluateOnExit` rule can have:

- **`action`** (required): Either `"RETRY"` or `"EXIT"` (case insensitive)
- **`onExitCode`** (optional): Glob pattern to match against the exit code (up to 512 characters). Can contain only numbers and can optionally end with `*` (e.g., `"1"`, `"13*"`)
- **`onStatusReason`** (optional): Glob pattern to match against the status reason (up to 512 characters). Can contain letters, numbers, periods, colons, white space, and can optionally end with `*`
- **`onReason`** (optional): Glob pattern to match against the reason string (up to 512 characters). Can contain letters, numbers, periods, colons, white space, and can optionally end with `*`

## Common Use Cases

### Retry on Spot Instance Interruptions

```python
resources:
    aws_batch_retry_strategy=json.dumps({
        "attempts": 3,
        "evaluateOnExit": [
            {
                "action": "RETRY",
                "onStatusReason": "Host EC2*"
            }
        ]
    })
```

### Retry on Out-of-Memory Errors

```python
resources:
    aws_batch_retry_strategy=json.dumps({
        "attempts": 2,
        "evaluateOnExit": [
            {
                "action": "RETRY",
                "onExitCode": "137"  # SIGKILL (OOM)
            }
        ]
    })
```

### Retry on Specific Exit Codes

```python
resources:
    aws_batch_retry_strategy=json.dumps({
        "attempts": 4,
        "evaluateOnExit": [
            {
                "action": "RETRY",
                "onExitCode": "1*"  # Retry on any exit code starting with 1
            },
            {
                "action": "EXIT",
                "onExitCode": "0"  # Don't retry on success
            }
        ]
    })
```

## Dynamic Retry Strategies

You can use Snakemake functions to dynamically generate retry strategies based on rule parameters or wildcards:

```python
def get_retry_strategy(wildcards, attempt):
    """Return retry strategy based on dataset size"""
    if wildcards.dataset == "large":
        return json.dumps({
            "attempts": 5,
            "evaluateOnExit": [
                {"action": "RETRY", "onExitCode": "137"},  # OOM
                {"action": "RETRY", "onStatusReason": "*timeout*"}
            ]
        })
    else:
        return json.dumps({"attempts": 2})

rule process_data:
    input:
        "data/{dataset}.txt"
    output:
        "results/{dataset}.out"
    resources:
        aws_batch_retry_strategy=get_retry_strategy
    shell:
        "process.sh {input} {output}"
```

**Note:** Like other complex resource parameters (`aws_batch_secrets`, `aws_batch_consumable_resources`), the value must be a JSON string, not a Python dict. Use `json.dumps()` to convert Python dicts to JSON strings.

# Example

## Create environment

Install snakemake and the AWS executor and storage plugins into an environment. We 
recommend the use of mamba package manager which can be [installed using miniforge](https://snakemake.readthedocs.io/en/stable/tutorial/setup.html#step-1-installing-miniforge), but these 
dependencies can also be installed using pip or other python package managers. 

```
mamba create -n snakemake-example \
    snakemake snakemake-storage-plugin-s3 snakemake-executor-plugin-aws-batch
mamba activate snakemake-example
```

Clone the snakemake tutorial repo containing the example workflow:

```
git clone https://github.com/snakemake/snakemake-tutorial-data.git
```

Setup and run tutorial workflow on the the executor

```
cd snakemake-tutorial-data 

export SNAKEMAKE_AWS_BATCH_REGION=
export SNAKEMAKE_AWS_BATCH_JOB_QUEUE=
export SNAKEMAKE_AWS_BATCH_JOB_ROLE=

snakemake --jobs 4 \
    --executor aws-batch \
    --aws-batch-region us-west-2 \
    --default-storage-provider s3 \
    --default-storage-prefix s3://snakemake-tutorial-example \
    --verbose
```








