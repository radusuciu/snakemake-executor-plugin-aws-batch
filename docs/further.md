# AWS Credentials

This plugin assumes you have setup AWS CLI credentials in ~/.aws/credentials. For more
information see [aws cli configuration](https://docs.aws.amazon.com/cli/v1/userguide/cli-configure-files.html).

# AWS Infrastructure Requirements

The snakemake-executor-plugin-aws-batch requires an EC2 compute environment and a job queue
to be configured. The plugin repo [contains terraform](https://github.com/snakemake/snakemake-executor-plugin-aws-batch/tree/main/terraform) used to setup 
the requisite AWS Batch infrastructure. 

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








