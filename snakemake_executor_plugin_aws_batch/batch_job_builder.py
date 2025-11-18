import json
import uuid
from typing import Any, List

from snakemake_interface_common.exceptions import WorkflowError
from snakemake_interface_executor_plugins.jobs import JobExecutorInterface

from snakemake_executor_plugin_aws_batch.batch_client import BatchClient
from snakemake_executor_plugin_aws_batch.constant import (
    BATCH_JOB_DEFINITION_TYPE,
    BATCH_JOB_PLATFORM_CAPABILITIES,
    BATCH_JOB_RESOURCE_REQUIREMENT_TYPE,
    VALID_RESOURCES_MAPPING,
)


class BatchJobBuilder:
    def __init__(
        self,
        logger,
        job: JobExecutorInterface,
        envvars: dict,
        container_image: str,
        settings,
        job_command: str,
        batch_client: BatchClient,
    ):
        self.logger = logger
        self.job = job
        self.envvars = envvars
        self.container_image = container_image
        self.settings = settings
        self.job_command = job_command
        self.batch_client = batch_client
        self.created_job_defs = []
        # Determine platform from job queue
        self.platform = self._get_platform_from_queue()

    def _make_container_command(self, remote_command: str) -> List[str]:
        """
        Return docker CMD form of the command
        """
        return ["/bin/bash", "-c", remote_command]

    def _get_platform_from_queue(self) -> str:
        """
        Determine the platform (EC2 or FARGATE) from the job queue's compute environments.

        :return: Platform capability string (EC2 or FARGATE)
        """
        try:
            # Get the job queue (supports per-rule override)
            job_queue = self._get_job_queue()

            # Query the job queue
            queue_response = self.batch_client.describe_job_queues(
                jobQueues=[job_queue]
            )

            if not queue_response.get("jobQueues"):
                self.logger.warning(
                    f"Job queue {job_queue} not found. Defaulting to EC2."
                )
                return BATCH_JOB_PLATFORM_CAPABILITIES.EC2.value

            job_queue_info = queue_response["jobQueues"][0]
            compute_env_order = job_queue_info.get("computeEnvironmentOrder", [])

            if not compute_env_order:
                self.logger.warning(
                    f"No compute environments found for queue {job_queue}. "
                    "Defaulting to EC2."
                )
                return BATCH_JOB_PLATFORM_CAPABILITIES.EC2.value

            # Get the first compute environment ARN
            compute_env_arn = compute_env_order[0]["computeEnvironment"]

            # Query the compute environment to get its type
            env_response = self.batch_client.describe_compute_environments(
                computeEnvironments=[compute_env_arn]
            )

            if not env_response.get("computeEnvironments"):
                self.logger.warning(
                    f"Compute environment {compute_env_arn} not found. Defaulting to EC2."
                )
                return BATCH_JOB_PLATFORM_CAPABILITIES.EC2.value

            compute_env = env_response["computeEnvironments"][0]

            # Check if it's a Fargate environment
            # Fargate environments have computeResources.type == "FARGATE" or "FARGATE_SPOT"
            compute_resources = compute_env.get("computeResources", {})
            resource_type = compute_resources.get("type", "")

            if resource_type in ["FARGATE", "FARGATE_SPOT"]:
                self.logger.info(
                    f"Detected FARGATE platform from queue {job_queue}"
                )
                return BATCH_JOB_PLATFORM_CAPABILITIES.FARGATE.value
            else:
                self.logger.info(
                    f"Detected EC2 platform from queue {job_queue}"
                )
                return BATCH_JOB_PLATFORM_CAPABILITIES.EC2.value

        except Exception as e:
            self.logger.warning(
                f"Failed to determine platform from queue: {e}. Defaulting to EC2."
            )
            return BATCH_JOB_PLATFORM_CAPABILITIES.EC2.value

    def _validate_fargate_resources(self, vcpu: int, mem: int) -> tuple[str, str]:
        """Validates vcpu and memory conform to Fargate requirements.

        Fargate requires strict memory/vCPU combinations.
        https://docs.aws.amazon.com/batch/latest/userguide/fargate.html
        """
        if mem in VALID_RESOURCES_MAPPING:
            if vcpu in VALID_RESOURCES_MAPPING[mem]:
                return str(vcpu), str(mem)
            else:
                raise WorkflowError(f"Invalid vCPU value {vcpu} for memory {mem} MB on Fargate")
        else:
            min_mem = min([m for m, v in VALID_RESOURCES_MAPPING.items() if vcpu in v])
            self.logger.warning(
                f"Memory value {mem} MB is invalid for vCPU {vcpu} on Fargate. "
                f"Setting memory to minimum allowed value {min_mem} MB."
            )
            return str(vcpu), str(min_mem)

    def _validate_secrets(self, secrets: List[dict], source: str) -> dict:
        """Validate secrets list and return as dict keyed by name.

        :param secrets: List of secret dicts to validate
        :param source: Description of where secrets came from (for error messages)
        :return: Dict mapping secret name to valueFrom
        :raises WorkflowError: If any secret is invalid
        """
        result = {}
        for secret in secrets:
            if not isinstance(secret, dict):
                raise WorkflowError(
                    f"{source} secret must be a dict with 'name' and 'valueFrom' keys, "
                    f"got {type(secret)}"
                )
            if "name" not in secret or "valueFrom" not in secret:
                raise WorkflowError(
                    f"{source} secret must have 'name' and 'valueFrom' keys, got {secret}"
                )
            result[secret["name"]] = secret["valueFrom"]
        return result

    def _parse_json_resource(self, resource_key: str, example: str = None) -> List[dict]:
        """Parse a JSON string resource value from job resources.

        Resources in Snakemake can be int, str, None, or callables that return those types.
        Callables are evaluated by Snakemake before execution, so we only receive the value.
        This method expects the resource value to be a JSON string containing a list.

        :param resource_key: The resource key to retrieve (e.g., "aws_batch_secrets")
        :param example: Optional example string to include in error messages
        :return: List of dicts parsed from the JSON string
        :raises WorkflowError: If the resource value cannot be parsed or is not a list
        """
        resource_value = self.job.resources.get(resource_key, None)

        if resource_value is None or resource_value == "":
            return []

        # Expect a JSON string (or the result of a callable that returned a JSON string)
        if not isinstance(resource_value, str):
            error_msg = f"{resource_key} must be a JSON string, got {type(resource_value)}."
            if example:
                error_msg += f" Example: {resource_key}='{example}'"
            raise WorkflowError(error_msg)

        # Parse JSON string
        try:
            parsed = json.loads(resource_value)
        except json.JSONDecodeError as e:
            raise WorkflowError(
                f"Failed to parse {resource_key} JSON: {e}. "
                f"Value was: {resource_value}"
            ) from e

        if not isinstance(parsed, list):
            raise WorkflowError(
                f"{resource_key} JSON must be a list, got {type(parsed)}"
            )

        return parsed

    def _parse_rule_secrets(self) -> List[dict]:
        """Parse per-rule secrets from job resources.

        :return: List of secret dicts parsed from the resource value
        :raises WorkflowError: If the resource value cannot be parsed
        """
        return self._parse_json_resource(
            "aws_batch_secrets",
            example='[{"name":"API_KEY","valueFrom":"arn:..."}]'
        )

    def _parse_rule_consumable_resources(self) -> List[dict]:
        """Parse per-rule consumable resources from job resources.

        :return: List of consumable resource dicts parsed from the resource value
        :raises WorkflowError: If the resource value cannot be parsed
        """
        return self._parse_json_resource(
            "aws_batch_consumable_resources",
            example='[{"consumableResource":"license-pool","quantity":2}]'
        )

    def _parse_rule_retry_strategy(self) -> dict:
        """Parse per-rule retry strategy from job resources.

        :return: Dict with retry strategy configuration
        :raises WorkflowError: If the resource value cannot be parsed
        """
        resource_value = self.job.resources.get("aws_batch_retry_strategy", None)

        if resource_value is None or resource_value == "":
            return {}

        # Expect a JSON string
        if not isinstance(resource_value, str):
            raise WorkflowError(
                f"aws_batch_retry_strategy must be a JSON string, got {type(resource_value)}. "
                'Example: aws_batch_retry_strategy=\'{"attempts": 3, "evaluateOnExit": [...]}\''
            )

        # Parse JSON string
        try:
            parsed = json.loads(resource_value)
        except json.JSONDecodeError as e:
            raise WorkflowError(
                f"Failed to parse aws_batch_retry_strategy JSON: {e}. "
                f"Value was: {resource_value}"
            ) from e

        if not isinstance(parsed, dict):
            raise WorkflowError(
                f"aws_batch_retry_strategy JSON must be a dict, got {type(parsed)}"
            )

        return parsed

    def _validate_retry_strategy(self, retry_strategy: dict) -> dict:
        """Validate retry strategy format and values.

        :param retry_strategy: Dict with retry strategy configuration
        :return: Validated retry strategy in AWS Batch format
        :raises WorkflowError: If validation fails
        """
        if not retry_strategy:
            return {}

        if not isinstance(retry_strategy, dict):
            raise WorkflowError(
                "aws_batch_retry_strategy must be a dict"
            )

        validated = {}

        # Validate attempts (optional, but recommended)
        if "attempts" in retry_strategy:
            try:
                attempts = int(retry_strategy["attempts"])
                if not 1 <= attempts <= 10:
                    raise WorkflowError(
                        f"Retry attempts must be between 1 and 10, got {attempts}"
                    )
                validated["attempts"] = attempts
            except (ValueError, TypeError) as e:
                raise WorkflowError(
                    f"Retry attempts must be an integer: {e}"
                ) from e

        # Validate evaluateOnExit (optional)
        if "evaluateOnExit" in retry_strategy:
            evaluate_on_exit = retry_strategy["evaluateOnExit"]

            if not isinstance(evaluate_on_exit, list):
                raise WorkflowError(
                    "evaluateOnExit must be a list of evaluation objects"
                )

            validated_evaluations = []
            for idx, evaluation in enumerate(evaluate_on_exit):
                if not isinstance(evaluation, dict):
                    raise WorkflowError(
                        f"evaluateOnExit[{idx}] must be a dict with 'action' key"
                    )

                # Validate action (required)
                if "action" not in evaluation:
                    raise WorkflowError(
                        f"evaluateOnExit[{idx}] must have 'action' key"
                    )

                # Normalize action to uppercase (AWS Batch accepts case-insensitive values)
                action = str(evaluation["action"]).upper()
                if action not in ["RETRY", "EXIT"]:
                    raise WorkflowError(
                        f"evaluateOnExit[{idx}] action must be 'RETRY' or 'EXIT', got '{action}'"
                    )

                validated_eval = {"action": action}

                # Optional fields: onStatusReason, onReason, onExitCode
                if "onStatusReason" in evaluation:
                    validated_eval["onStatusReason"] = str(evaluation["onStatusReason"])

                if "onReason" in evaluation:
                    validated_eval["onReason"] = str(evaluation["onReason"])

                if "onExitCode" in evaluation:
                    # Can be a string like "1" or "*" or a pattern like "1:10"
                    validated_eval["onExitCode"] = str(evaluation["onExitCode"])

                validated_evaluations.append(validated_eval)

            if validated_evaluations:
                validated["evaluateOnExit"] = validated_evaluations

        return validated

    def _get_retry_strategy(self) -> dict:
        """Extract and validate retry strategy from job resources.

        Retry strategy allows configuring automatic retries for failed jobs,
        including conditional retry logic based on exit codes and status reasons.

        :return: Retry strategy configuration in AWS Batch format
        """
        # Parse retry strategy from JSON string
        retry_strategy = self._parse_rule_retry_strategy()

        if not retry_strategy:
            return {}

        return self._validate_retry_strategy(retry_strategy)

    def _merge_secrets(self) -> List[dict]:
        """Merge global and per-rule secrets.

        Per-rule secrets take precedence over global secrets when both define
        the same environment variable name.

        :return: List of secret dicts with 'name' and 'valueFrom' keys
        """
        # Merge global and rule secrets (rule secrets override global)
        secrets_dict = {
            **self._validate_secrets(self.settings.secrets or [], "Global"),
            **self._validate_secrets(self._parse_rule_secrets(), "Rule")
        }

        # Convert back to list format for AWS Batch
        return [{"name": name, "valueFrom": value_from}
                for name, value_from in secrets_dict.items()]

    def _validate_timeout(self, timeout_value: Any, source: str) -> int:
        """Validate timeout value meets AWS Batch requirements.

        :param timeout_value: The timeout value to validate
        :param source: Description of where timeout came from (for error messages)
        :return: Validated timeout as integer
        :raises WorkflowError: If timeout value is invalid
        """
        try:
            timeout_int = int(timeout_value)
        except (ValueError, TypeError) as e:
            raise WorkflowError(
                f"{source} timeout must be an integer, got {type(timeout_value)}: {timeout_value}"
            ) from e

        if timeout_int < 60:
            raise WorkflowError(
                f"{source} timeout must be at least 60 seconds, got {timeout_int}"
            )

        return timeout_int

    def _get_timeout(self) -> int:
        """Get timeout value from per-rule resource or fall back to global setting.

        Per-rule timeout takes precedence over global task_timeout setting.

        :return: Timeout in seconds (minimum 60)
        :raises WorkflowError: If timeout value is invalid
        """
        # Check for per-rule timeout
        rule_timeout = self.job.resources.get("aws_batch_timeout", None)

        if rule_timeout is not None:
            return self._validate_timeout(rule_timeout, "Per-rule")

        # Fall back to global setting
        return self._validate_timeout(self.settings.task_timeout, "Global")

    def _get_job_queue(self) -> str:
        """Get job queue from per-rule resource or fall back to global setting.

        Per-rule job queue takes precedence over global job_queue setting.

        Returns:
            Job queue ARN or name

        Raises:
            WorkflowError: If job queue value is invalid
        """
        # Check for per-rule job queue
        rule_queue = self.job.resources.get("aws_batch_job_queue", None)

        if rule_queue is not None:
            if not isinstance(rule_queue, str):
                raise WorkflowError(
                    f"aws_batch_job_queue must be a string, got {type(rule_queue)}"
                )
            return rule_queue

        # Fall back to global setting
        return self.settings.job_queue

    def _validate_ec2_resources(self, vcpu: int, mem: int) -> tuple[str, str]:
        """Validates vcpu and memory for EC2 compute environments.

        EC2 allows flexible resource allocation - just basic sanity checks.
        https://docs.aws.amazon.com/batch/latest/userguide/compute_environment_parameters.html
        """
        if vcpu < 1:
            raise WorkflowError(f"vCPU must be at least 1, got {vcpu}")
        if mem < 1024:
            raise WorkflowError(f"Memory must be at least 1024 MiB, got {mem} MiB")
        return str(vcpu), str(mem)

    def _validate_resources(self, vcpu: str, mem: str) -> tuple[str, str]:
        """Validates vcpu and memory based on platform requirements.

        https://docs.aws.amazon.com/batch/latest/APIReference/API_ResourceRequirement.html
        """
        vcpu_int = int(vcpu)
        mem_int = int(mem)

        if self.platform == BATCH_JOB_PLATFORM_CAPABILITIES.FARGATE.value:
            return self._validate_fargate_resources(vcpu_int, mem_int)
        else:
            return self._validate_ec2_resources(vcpu_int, mem_int)

    def _validate_consumable_resources(self, resources: list) -> list:
        """Validate consumable resources format and values.

        :param resources: List of consumable resource dicts
        :return: Validated consumable resources in AWS Batch format
        :raises WorkflowError: If validation fails
        """
        if not isinstance(resources, list):
            raise WorkflowError(
                "aws_batch_consumable_resources must be a list of dicts"
            )

        validated_resources = []
        for resource in resources:
            if not isinstance(resource, dict):
                raise WorkflowError(
                    "Each consumable resource must be a dict with "
                    "'consumableResource' and 'quantity' keys"
                )

            if "consumableResource" not in resource:
                raise WorkflowError(
                    "Consumable resource must have 'consumableResource' key"
                )

            if "quantity" not in resource:
                raise WorkflowError(
                    "Consumable resource must have 'quantity' key"
                )

            # Validate quantity is a positive number
            try:
                quantity = int(resource["quantity"])
                if quantity <= 0:
                    raise WorkflowError(
                        f"Consumable resource quantity must be positive, got {quantity}"
                    )
            except (ValueError, TypeError) as e:
                raise WorkflowError(
                    f"Consumable resource quantity must be a number: {e}"
                ) from e

            validated_resources.append({
                "consumableResource": str(resource["consumableResource"]),
                "quantity": quantity
            })

        return validated_resources

    def _get_consumable_resources(self) -> list:
        """Extract and validate consumable resources from job resources.

        Consumable resources are rate-limited resources like licenses or database
        connections that can be specified at the rule level.

        :return: List of consumable resource requirements in AWS Batch format
        """
        # Parse consumable resources from JSON string
        consumable_resources = self._parse_rule_consumable_resources()

        if not consumable_resources:
            return []

        return self._validate_consumable_resources(consumable_resources)

    def build_job_definition(self):
        job_uuid = str(uuid.uuid4())

        # Support optional custom suffix via aws_batch_job_name_suffix resource
        custom_suffix = self.job.resources.get("aws_batch_job_name_suffix", None)
        if custom_suffix:
            job_name = f"snakejob-{self.job.name}-{custom_suffix}-{job_uuid}"
            job_definition_name = f"snakejob-def-{self.job.name}-{custom_suffix}-{job_uuid}"
        else:
            job_name = f"snakejob-{self.job.name}-{job_uuid}"
            job_definition_name = f"snakejob-def-{self.job.name}-{job_uuid}"

        # Validate and convert resources
        gpu = max(0, int(self.job.resources.get("_gpus", 0)))
        vcpu = max(1, int(self.job.resources.get("_cores", 1)))  # Default to 1 vCPU
        mem = max(1, int(self.job.resources.get("mem_mb", 1024)))  # Default to 1024 MiB

        vcpu_str, mem_str = self._validate_resources(str(vcpu), str(mem))
        gpu_str = str(gpu)

        environment = []
        if self.envvars:
            environment = [{"name": k, "value": v} for k, v in self.envvars.items()]

        secrets = self._merge_secrets()

        # Validate that execution role is provided when secrets are configured
        if secrets and not self.settings.execution_role:
            raise WorkflowError(
                "AWS Batch requires an execution role ARN when using secrets. "
                "Please provide --aws-batch-execution-role with the ARN of an IAM role "
                "that has permissions to access AWS Secrets Manager."
            )

        container_properties = {
            "image": self.container_image,
            # command requires a list of strings (docker CMD format)
            "command": self._make_container_command(self.job_command),
            "environment": environment,
            "jobRoleArn": self.settings.job_role,
            "privileged": True,
            "resourceRequirements": [
                {
                    "type": BATCH_JOB_RESOURCE_REQUIREMENT_TYPE.VCPU.value,
                    "value": vcpu_str,
                },
                {
                    "type": BATCH_JOB_RESOURCE_REQUIREMENT_TYPE.MEMORY.value,
                    "value": mem_str,
                },
            ],
        }

        # Add execution role if provided (required for secrets)
        if self.settings.execution_role:
            container_properties["executionRoleArn"] = self.settings.execution_role

        # Add secrets if any are configured
        if secrets:
            container_properties["secrets"] = secrets

        if gpu > 0:
            container_properties["resourceRequirements"].append(
                {
                    "type": BATCH_JOB_RESOURCE_REQUIREMENT_TYPE.GPU.value,
                    "value": gpu_str,
                }
            )

        timeout = {"attemptDurationSeconds": self._get_timeout()}
        tags = self.settings.tags if isinstance(self.settings.tags, dict) else dict()

        # Build job definition parameters
        job_def_params = {
            "jobDefinitionName": job_definition_name,
            "type": BATCH_JOB_DEFINITION_TYPE.CONTAINER.value,
            "containerProperties": container_properties,
            "timeout": timeout,
            "tags": tags,
            "platformCapabilities": [self.platform],
        }

        # Add consumable resources if specified (top-level parameter, not in containerProperties)
        consumable_resources = self._get_consumable_resources()
        if consumable_resources:
            job_def_params["consumableResourceProperties"] = {
                "consumableResourceList": consumable_resources
            }

        # Add retry strategy if specified
        retry_strategy = self._get_retry_strategy()
        if retry_strategy:
            job_def_params["retryStrategy"] = retry_strategy

        try:
            job_def = self.batch_client.register_job_definition(**job_def_params)
            self.created_job_defs.append(job_def)
            return job_def, job_name
        except Exception as e:
            raise WorkflowError(f"Failed to register job definition: {e}") from e

    def submit(self):
        job_def, job_name = self.build_job_definition()

        job_params = {
            "jobName": job_name,
            "jobQueue": self._get_job_queue(),
            "jobDefinition": "{}:{}".format(
                job_def["jobDefinitionName"], job_def["revision"]
            ),
        }

        try:
            submitted = self.batch_client.submit_job(**job_params)
            return submitted
        except Exception as e:
            raise WorkflowError(f"Failed to submit job: {e}") from e
