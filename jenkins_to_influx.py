#!/usr/bin/env python3
import os
import sys
import requests
import urllib.parse
from datetime import datetime
from requests.auth import HTTPBasicAuth

# === CONFIG ===
JENKINS_URL = os.getenv("JENKINS_URL").rstrip("/")
JENKINS_USER = os.getenv("JENKINS_USER")
JENKINS_TOKEN = os.getenv("JENKINS_TOKEN")
INFLUX_URL   = os.getenv("INFLUX_URL").rstrip("/")
INFLUX_DB    = os.getenv("INFLUX_DB", "jenkins")
MEASUREMENT  = os.getenv("MEASUREMENT", "jenkins_custom_data")

if not JENKINS_USER or not JENKINS_TOKEN:
    print(" Please set JENKINS_USER and JENKINS_TOKEN")
    sys.exit(1)

auth = HTTPBasicAuth(JENKINS_USER, JENKINS_TOKEN)

def get_json(url):
    try:
        r = requests.get(url, auth=auth, timeout=20)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f" Failed: {url} -> {e}")
        return None

def already_in_influx(job, build_number):
    q = f"SELECT build_number FROM {MEASUREMENT} WHERE project_name='{job}' AND build_number={build_number}"
    resp = requests.get(f"{INFLUX_URL}/query", params={"db": INFLUX_DB, "q": q})
    return "series" in resp.text if resp.ok else False

def write_to_influx(job, build):
    ts = build["timestamp"] * 1_000_000
    result = build.get("result", "UNKNOWN")
    duration = build.get("duration", 0)
    build_num = build["number"]
    time_str = datetime.fromtimestamp(build["timestamp"]/1000).strftime('%Y-%m-%dT%H:%M:%SZ')

    line = f"{MEASUREMENT},project_name={job} build_number={build_num}i,build_duration={duration}i,build_result=\"{result}\",build_time=\"{time_str}\" {ts}"
    resp = requests.post(f"{INFLUX_URL}/write", params={"db": INFLUX_DB}, data=line)
    if resp.ok:
        print(f"✅ {job} #{build_num} -> {result}")
    else:
        print(f"❌ Influx insert failed for {job} #{build_num}")

def main():
    views = get_json(f"{JENKINS_URL}/api/json?tree=views[name,jobs[name]]")
    if not views: sys.exit(1)

    for v in views.get("views", []):
        for job in v.get("jobs", []):
            job_name = job["name"]
            builds = get_json(f"{JENKINS_URL}/job/{job_name}/api/json?tree=builds[number,timestamp,duration,result]")
            if not builds: continue

            for b in builds.get("builds", []):
                num = b["number"]
                if not already_in_influx(job_name, num):
                    write_to_influx(job_name, b)

if __name__ == "__main__":
    main()
