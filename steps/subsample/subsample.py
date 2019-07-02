import requests, psycopg2, boto3 
import pickle, os, random, urllib.parse
import numpy as np
import datetime, argparse
from hydro_serving_grpc.timemachine.reqstore_client import *


s3 = boto3.resource('s3')


def get_model_version_id(host_address, application_name):
    addr = urllib.parse.urljoin(host_address, f"api/v2/application/{application_name}")
    resp = requests.get(addr).json()
    assert resp.get("error") is None, resp.get("message")
    return resp["executionGraph"]["stages"][0]["modelVariants"][0]["modelVersion"]["id"]


def main(hydrosphere_address, application_name, is_dev=False, is_aws=False, storage_path="./"):

    # Define required variables
    namespace = urllib.parse.urlparse(hydrosphere_address).netloc.split(".")[0]
    data_path = os.path.join(namespace, "data", "mnist", str(round(datetime.datetime.now().timestamp())))
    reqstore_address = urllib.parse.urljoin(hydrosphere_address, "reqstore")
    
    postgres_host = "postgres"  # Use Kubernetes service to find postgres deployment
    postgres_pass = "hydro-serving"
    postgres_user = "serving"
    postgres_port = "5432"
    postgres_db   = "postgres"

    client = ReqstoreHttpClient(reqstore_address)
    model_version_id = str(get_model_version_id(hydrosphere_address, application_name))

    conn = psycopg2.connect(
        f"postgresql://{postgres_user}:{postgres_pass}@{postgres_host}:{postgres_port}/{postgres_db}"
    )
    cur = conn.cursor()

    cur.execute('''
        CREATE TABLE IF NOT EXISTS 
            requests (timestamp bigint, uid integer, ground_truth integer);
    ''')

    print("Sample data from reqstore", flush=True)
    records = list(
        client.getRange(0, 1854897851804888100, model_version_id, limit=10000, reverse="false"))
    random.shuffle(records)

    print("Prepare dataset", flush=True)
    imgs, labels = list(), list()
    for timestamp in records:

        for entry in timestamp.entries:
            cur.execute("SELECT * FROM requests WHERE timestamp=%s AND uid=%s", (timestamp.ts, entry.uid))
            db_record = cur.fetchone()

            if not db_record: continue    
            
            request_image = np.array(entry.request.inputs["imgs"].float_val)
            request_image = request_image.reshape((28, 28))
            imgs.append(request_image); labels.append(db_record[2])

    if not imgs:
        imgs, labels = np.empty((0, 28, 28)), np.empty((0,))
    else: 
        imgs, labels = np.array(imgs), np.array(labels)
        
    train_imgs, train_labels = imgs[:int(len(imgs) * 0.75)], labels[:int(len(labels) * 0.75)]
    test_imgs, test_labels = imgs[int(len(imgs) * 0.75):], labels[int(len(labels) * 0.75):]

    assert len(train_imgs) > 0, "Not enough training data"
    assert len(test_imgs) > 0, "Not enough testing data"

    print(f"Train subsample size: {len(train_imgs)}", flush=True)
    print(f"Test subsample size: {len(test_imgs)}", flush=True)
    
    np.savez_compressed(os.path.join(storage_path, "train.npz"), imgs=train_imgs, labels=train_labels)
    np.savez_compressed(os.path.join(storage_path, "test.npz"), imgs=test_imgs, labels=test_labels)

    # Upload files to S3 
    for filename in ["train.npz", "test.npz"]:
        filename = os.path.join(storage_path, filename)
        print(f"Uploading {filename} to S3", flush=True)
        s3.meta.client.upload_file(
            filename, "odsc-workshop", os.path.join(data_path, filename))

    # Dump Dataset path:
    # AWS
    if is_aws: return {"data_path": data_path}

    # Kubeflow 
    with open("./data_path.txt" if is_dev else "/data_path.txt", "w+") as file:
        file.write(data_path)


def aws_lambda(event, context):
    return main(
        hydrosphere_address=event["hydrosphere_address"],
        application_name=event["application_name"],
        is_aws=True,
        storage_path="/tmp/"
    )


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument('--hydrosphere-address', required=True)
    parser.add_argument('--application-name', required=True)
    parser.add_argument(
        '--dev', help='Flag for development purposes', action="store_true")
    
    args = parser.parse_args()
    main(
        hydrosphere_address=args.hydrosphere_address,
        application_name=args.application_name,
        is_dev=args.dev,
    )
