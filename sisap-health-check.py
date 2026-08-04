#!/usr/bin/env python3
import click
import requests
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import datetime
from functools import partial
from tqdm import tqdm
from pathlib import Path
import json
import yaml
import tempfile
import zipfile
import shutil
from os import environ
from subprocess import check_output
from tira.io_utils import parse_prototext_key_values


def track_execution(func, retries=3, timeout=300):
    last_exception = None

    for attempt in range(1, retries + 1):
        start_time = time.perf_counter()

        try:
            # Use ThreadPoolExecutor to enforce the timeout
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(func)
                result = future.result(timeout=timeout)
                result["time"] = time.perf_counter() - start_time
                return result

        except TimeoutError:
            print(f"Attempt {attempt} failed: Execution timed out after {timeout}s")
            last_exception = Exception(f"Function timed out after {timeout} seconds")
        except Exception as e:
            print(f"Attempt {attempt} failed with error: {e}")
            last_exception = e
        finally:
            pass


ALL_TESTS = {}

def load_test_matrix():
    with open(Path(__file__).parent / "test-matrix.yml") as f:
        matrix = yaml.safe_load(f)
        return matrix


def download_dataset(dataset):
    check_output(["tira-cli", "download", "--dataset", dataset])
    check_output(["tira-cli", "download", "--dataset", dataset, "--truths"])

    return {"dataset_id": dataset}

def populate_download_datasets_from_tira():
    datasets = set()
    for syste_name, system in load_test_matrix()["systems"].items():
        for e in system["datasets"]:
            datasets.add(e)
    for dataset in datasets:
        test_name = f"download-dataset-{dataset}"
        test_execution = partial(
            download_dataset,
            dataset
        )
        ALL_TESTS[test_name] = test_execution  


def run_sisap_system_test(sisap_system, dataset):
    cmd = [
        "tira-cli", "run", "local", "--approach",
        "sisap-2026/" + sisap_system, "--input", dataset
    ]

    results = check_output(cmd)
    out_dir = results.decode("UTF-8").split("Full evaluation results: ")[1].split("\n")[0]
    ret = {"sisap_system": sisap_system, "dataset_id": dataset}
    
    eval_file = Path(out_dir) / "evaluation.prototext"
    ret["evaluation"] = {
        measure["key"]: measure["value"]
        for measure in parse_prototext_key_values(eval_file)
    }
    
    return ret


def populate_run_sisap_systems_tests(run_dir):
    for system_name, system in load_test_matrix()["systems"].items():
        for dataset in system["datasets"]:
            test_name = f"run-{system_name}-{dataset}"
            test_execution = partial(
                run_sisap_system_test,
                system_name,
                dataset
            )
            ALL_TESTS[test_name] = test_execution

@click.command()
@click.argument("output_file")
def main(output_file):
    current_iso = datetime.now().isoformat()
    ret = []

    populate_download_datasets_from_tira()
    populate_run_sisap_systems_tests(tempfile.mkdtemp())
    
    for test_name, test in tqdm(ALL_TESTS.items()):
        try:
            result = track_execution(test)
        except:
            result = {"status": "failed"}
        result["name"] = test_name
        result["timestamp"] = current_iso
        ret.append(result)

    Path(output_file).parent.mkdir(exist_ok=True, parents=True)

    if not Path(output_file).is_file():
        Path(output_file).touch()

    with open(output_file, "a") as f:
        for l in ret:
            f.write(json.dumps(l) + "\n")

if __name__ == '__main__':
    main()
