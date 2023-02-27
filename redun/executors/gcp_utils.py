from enum import Enum
from typing import Dict, Iterable, List, Tuple, Union

from google.api_core.gapic_v1 import client_info
from google.cloud import batch_v1


# List of supported available CPU Platforms
# https://cloud.google.com/compute/docs/instances/specify-min-cpu-platform#availablezones
class MinCPUPlatform(Enum):
    XEON_ICE_LAKE = "Intel Ice Lake"
    XEON_CASCADE_LAKE = "Intel Cascade Lake"
    XEON_SKYLAKE = "Intel Skylake"
    XEON_BROADWELL = "Intel Broadwell"
    XEON_HASWELL = "Intel Haswell"
    XEON_SANDY_BRIDGE = "Intel Sandy Bridge"
    EPYC_ROME = "AMD Rome"
    EPYC_MILAN = "AMD Milan"


def get_gcp_client(
    sync: bool = True,
) -> Union[batch_v1.BatchServiceClient, batch_v1.BatchServiceAsyncClient]:
    c_info = client_info.ClientInfo(user_agent='redun')
    return batch_v1.BatchServiceClient(client_info=c_info) if sync else batch_v1.BatchServiceAsyncClient(client_info=c_info)


def batch_submit(
    client: Union[batch_v1.BatchServiceClient, batch_v1.BatchServiceAsyncClient],
    job_name: str,
    project: str,
    region: str,
    gcs_bucket: str,
    mount_path: str,
    machine_type: str,
    vcpus: int,
    memory: int,
    task_count: int,
    max_duration: str,
    retries: int,
    priority: int,
    boot_disk_size_gb: int = None,
    min_cpu_platform: MinCPUPlatform = None,
    accelerators: List[Tuple[str, int]] = [],
    image: str = None,
    script: str = "exit 0",
    entrypoint: str = None,
    commands: List[str] = ["exit 0"],
    service_account_email: str = "",
    labels: Dict[str, str] = {},
    **kwargs,  # Ignore extra args
) -> batch_v1.Job:
    # Define what will be done as part of the job.
    runnable = batch_v1.Runnable()
    if image is None:
        runnable.script = batch_v1.Runnable.Script()
        runnable.script.text = script
        # You can also run a script from a file. Just remember, that needs to be a script that's
        # already on the VM that will be running the job. Using runnable.script.text and
        # runnable.script.path is mutually exclusive.
        # runnable.script.path = '/tmp/test.sh'
    else:
        # Setup
        setup_runnable = batch_v1.Runnable()
        setup_runnable.script = batch_v1.Runnable.Script()
        setup_runnable.script.text = commands['stage']

        # Run Job
        runnable.container = batch_v1.Runnable.Container()
        runnable.container.image_uri = image
        runnable.container.entrypoint = "/bin/bash"
        runnable.container.commands = ["run.sh"] #commands['run']
        runnable.container.volumes = ['/workspace:/workspace']
        runnable.container.options = '-w /workspace'

        # Teardown
        teardown_runnable = batch_v1.Runnable()
        teardown_runnable.always_run=True
        teardown_runnable.script = batch_v1.Runnable.Script()
        teardown_runnable.script.text = commands['unstage']


    task = batch_v1.TaskSpec()
    task.runnables = [setup_runnable, runnable, teardown_runnable]

    # We can specify what resources are requested by each task.
    resources = batch_v1.ComputeResource()
    resources.cpu_milli = vcpus * 1000  # in milliseconds per cpu-second.
    # This means the task requires 2 whole CPUs with default value.
    resources.memory_mib = memory
    if boot_disk_size_gb:
        resources.boot_disk_mib = boot_disk_size_gb * 1000
    task.compute_resource = resources

    task.max_retry_count = retries
    task.max_run_duration = max_duration

    # Tasks are grouped inside a job using TaskGroups.
    # Currently, it's possible to have only one task group.
    group = batch_v1.TaskGroup()
    group.task_count = task_count
    group.task_spec = task

    # Policies are used to define on what kind of virtual machines the tasks will run on.
    # Read more about machine types here: https://cloud.google.com/compute/docs/machine-types
    allocation_policy = batch_v1.AllocationPolicy()
    policy = batch_v1.AllocationPolicy.InstancePolicy()
    policy.machine_type = machine_type
    policy.min_cpu_platform = min_cpu_platform

    def create_accelerator(typ, count):
        accelerator = batch_v1.AllocationPolicy.Accelerator()
        accelerator.type_ = type
        accelerator.count = count
        return accelerator

    policy.accelerators = list(map(lambda a: create_accelerator(a[0], a[1]), accelerators))

    instances = batch_v1.AllocationPolicy.InstancePolicyOrTemplate()
    if policy.accelerators:
        instances.install_gpu_drivers = True
    instances.policy = policy
    allocation_policy.instances = [instances]

    if service_account_email:
        service_account = batch_v1.ServiceAccount()
        service_account.email = service_account_email
        allocation_policy.service_account = service_account

    job = batch_v1.Job()
    job.priority = priority
    job.task_groups = [group]
    job.allocation_policy = allocation_policy
    job.labels = labels

    # We use Cloud Logging as it's an out of the box available option
    job.logs_policy = batch_v1.LogsPolicy()
    job.logs_policy.destination = batch_v1.LogsPolicy.Destination.CLOUD_LOGGING

    create_request = batch_v1.CreateJobRequest()
    create_request.job = job
    create_request.job_id = job_name
    # The job's parent is the region in which the job will run
    create_request.parent = f"projects/{project}/locations/{region}"
    return client.create_job(create_request)


def list_jobs(
    client: batch_v1.BatchServiceClient, project_id: str, region: str
) -> Iterable[batch_v1.Job]:
    """
    Get a list of all jobs defined in given region.

    Args:
        project_id: project ID or project number of the Cloud project you want to use.
        region: name of the region hosting the jobs.

    Returns:
        An iterable collection of Job object.
    """
    return client.list_jobs(parent=f"projects/{project_id}/locations/{region}")


def format_job_name(project_id: str, region: str, job_name: str) -> str:
    return f"projects/{project_id}/locations/{region}/jobs/{job_name}"


def get_job(client: batch_v1.BatchServiceClient, job_name: str) -> batch_v1.Job:
    """
    Retrieve information about a Batch Job.

    Args:
        project_id: project ID or project number of the Cloud project you want to use.
        region: name of the region hosts the job.
        job_name: the name of the job you want to retrieve information about.

    Returns:
        A Job object representing the specified job.
    """
    return client.get_job(name=job_name)


def format_task_group_name(project_id: str, region: str, job_name: str, group_name: str) -> str:
    return f"projects/{project_id}/locations/{region}/jobs/{job_name}/taskGroups/{group_name}"


def list_tasks(client: batch_v1.BatchServiceClient, group_name: str) -> Iterable[batch_v1.Task]:
    """
    Get a list of all jobs defined in given region.

    Args:
        project_id: project ID or project number of the Cloud project you want to use.
        region: name of the region hosting the jobs.
        job_name: name of the job which tasks you want to list.
        group_name: name of the group of tasks. Usually it's `group0`.

    Returns:
        An iterable collection of Task objects.
    """
    return client.list_tasks(parent=group_name)


def format_task_name(
    project_id: str, region: str, job_name: str, group_name: str, task_number: int
) -> str:
    return (
        f"projects/{project_id}/locations/{region}/jobs/{job_name}"
        f"/taskGroups/{group_name}/tasks/{task_number}"
    )


def get_task(client: batch_v1.BatchServiceClient, task_name: str) -> batch_v1.Task:
    """
    Retrieve information about a Task.

    Args:
        project_id: project ID or project number of the Cloud project you want to use.
        region: name of the region hosts the job.
        job_name: the name of the job you want to retrieve information about.
        group_name: the name of the group that owns the task you want to check.
            Usually it's `group0`.
        task_number: number of the task you want to look up.

    Returns:
        A Task object representing the specified task.
    """
    return client.get_task(name=task_name)
