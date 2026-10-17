"""Change the local demo's health response without exposing its key on the command line."""

import argparse
import os

import requests
from dotenv import load_dotenv

load_dotenv()
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("mode", choices=["healthy", "down", "slow"])
args = parser.parse_args()
response = requests.post(
    os.getenv("DEMO_BASE_URL", "http://127.0.0.1:5055") + "/control",
    headers={"X-Demo-Key": os.environ["DEMO_CONTROL_KEY"]},
    json={"mode": args.mode},
    timeout=5,
)
response.raise_for_status()
print(response.json())
