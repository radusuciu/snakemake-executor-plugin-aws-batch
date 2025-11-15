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

Specify consumable resources at the rule level using the `aws_batch_consumable_resources` resource parameter. The value should be a list of dictionaries, each containing:
- `consumableResource`: The name of the consumable resource
- `quantity`: The number of units required (must be a positive integer)

```python
rule licensed_analysis:
    input:
        "data.txt"
    output:
        "analysis.txt"
    resources:
        aws_batch_consumable_resources=[
            {"consumableResource": "license-pool", "quantity": 2}
        ]
    shell:
        "run_analysis.sh {input} {output}"
```

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








