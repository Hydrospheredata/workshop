import kfp.dsl as dsl 
from kfp.aws import use_aws_secret
import kubernetes.client.models as k8s
import argparse


@dsl.pipeline(name="mnist", description="MNIST classifier")
def pipeline_definition(
    hydrosphere_address,
    mount_path='/storage',
    learning_rate="0.01",
    epochs="10",
    batch_size="256",
    model_name="mnist",
    acceptable_accuracy="0.90",
):

    # 1. Download MNIST data
    download = dsl.ContainerOp(
        name="download",
        image="tidylobster/mnist-pipeline-download:latest",  # <-- Replace with correct docker image
        file_outputs={"data_path": "/data_path.txt"},
        arguments=["--hydrosphere-address", hydrosphere_address]
    ).apply(use_aws_secret())

    # 2. Train and save a MNIST classifier using Tensorflow
    train = dsl.ContainerOp(
        name="train",
        image="tidylobster/mnist-pipeline-train:latest",  # <-- Replace with correct docker image
        file_outputs={
            "accuracy": "/accuracy.txt",
            "model_path": "/model_path.txt",
        },
        arguments=[
            "--data-path", download.outputs["data_path"], 
            "--learning-rate", learning_rate,
            "--epochs", epochs,
            "--batch-size", batch_size,
            "--hydrosphere-address", hydrosphere_address
        ]
    ).apply(use_aws_secret())
    train.after(download)
    
    train.set_memory_request('1G')
    train.set_cpu_request('1')

    # 3. Release trained model to the cluster
    release = dsl.ContainerOp(
        name="release",
        image="tidylobster/mnist-pipeline-release:latest",  # <-- Replace with correct docker image
        file_outputs={"model_version": "/model_version.txt"},
        arguments=[
            "--data-path", download.outputs["data_path"],
            "--model-name", model_name,
            "--models-path", train.outputs["model_path"],
            "--accuracy", train.outputs["accuracy"],
            "--hydrosphere-address", hydrosphere_address,
            "--learning-rate", learning_rate,
            "--epochs", epochs,
            "--batch-size", batch_size,
        ]
    ).apply(use_aws_secret())
    release.after(train)
    
    # 4. Deploy model to stage application
    deploy_to_stage = dsl.ContainerOp(
        name="deploy_to_stage",
        image="tidylobster/mnist-pipeline-deploy-to-stage:latest",  # <-- Replace with correct docker image
        file_outputs={"stage_app_name": "/stage_app_name.txt"},
        arguments=[
            "--model-version", release.outputs["model_version"],
            "--hydrosphere-address", hydrosphere_address,
            "--model-name", model_name,
        ],
    ).apply(use_aws_secret())
    deploy_to_stage.after(release)

    # 5. Test the model via stage application
    test = dsl.ContainerOp(
        name="test",
        image="tidylobster/mnist-pipeline-test:latest",  # <-- Replace with correct docker image
        arguments=[
            "--data-path", download.outputs["data_path"],
            "--hydrosphere-address", hydrosphere_address,
            "--acceptable-accuracy", acceptable_accuracy,
            "--model-name", model_name, 
        ],
    ).apply(use_aws_secret())
    test.after(deploy_to_stage)

    test.set_retry(3)

    # 6. Deploy model to production application
    deploy_to_prod = dsl.ContainerOp(
        name="deploy_to_prod",
        image="tidylobster/mnist-pipeline-deploy-to-prod:latest",  # <-- Replace with correct docker image
        arguments=[
            "--model-version", release.outputs["model_version"],
            "--model-name", model_name,
            "--hydrosphere-address", hydrosphere_address
        ],
    ).apply(use_aws_secret())
    deploy_to_prod.after(test)


if __name__ == "__main__":
    import kfp.compiler as compiler
    import subprocess, sys

    # Acquire parameters
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-f', '--file', help='New pipeline file', default="pipeline.tar.gz")
    parser.add_argument(
        '-n', '--namespace', help="Namespace, where kubeflow and serving are running", required=True)
    args = parser.parse_args()

    # Compile pipeline
    compiler.Compiler().compile(pipeline_definition, args.file)

    # Replace hardcoded namespaces
    untar = f"tar -xvf {args.file}"
    replace_minio = f"sed -i '' s/minio-service.kubeflow/minio-service.{args.namespace}/g pipeline.yaml"
    replace_pipeline_runner = f"sed -i '' s/pipeline-runner/{args.namespace}-pipeline-runner/g pipeline.yaml"

    process = subprocess.run(untar.split())
    process = subprocess.run(replace_minio.split())
    process = subprocess.run(replace_pipeline_runner.split())