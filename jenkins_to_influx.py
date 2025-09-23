import os
import sys
import requests
from influxdb import InfluxDBClient
from datetime import datetime

# -----------------------------
# Environment Variables
# -----------------------------
JENKINS_URL = os.getenv("JENKINS_URL", "http://localhost:8080").rstrip("/")
JENKINS_USER = os.getenv("JENKINS_USER", "")
JENKINS_TOKEN = os.getenv("JENKINS_TOKEN", "")

INFLUX_URL = os.getenv("INFLUX_URL", "http://localhost:8086")
INFLUX_DB = os.getenv("INFLUX_DB", "jenkins")
MEASUREMENT = os.getenv("MEASUREMENT", "jenkins_custom_data")

# Parse Influx host and port from URL
from urllib.parse import urlparse
influx = urlparse(INFLUX_URL)
influx_host = influx.hostname
influx_port = influx.port or 8086

client = InfluxDBClient(host=influx_host, port=influx_port)
client.switch_database(INFLUX_DB)

# -----------------------------
# Jenkins API Helpers
# -----------------------------
def get_json(url):
    try:
        resp = requests.get(url, auth=(JENKINS_USER, JENKINS_TOKEN), timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[ERROR] Failed fetching {url}: {e}")
        return None


def get_causer(build):
    """Extract user who triggered the build"""
    actions = build.get("actions", [])
    for act in actions:
        causes = act.get("causes", [])
        for c in causes:
            if "userName" in c:
                return c["userName"]
    return "SYSTEM"


# -----------------------------
# InfluxDB Helpers
# -----------------------------
def already_in_influx(job_name, build_number, view):
    query = f'SELECT * FROM "{MEASUREMENT}" WHERE "project"=\'{job_name}\' AND "build_number"={build_number} AND "view"=\'{view}\''
    result = client.query(query)
    return len(list(result.get_points())) > 0


def write_to_influx(job_name, build, view, causer):
    build_number = build["number"]
    result = build.get("result", "UNKNOWN")
    duration = build.get("duration", 0)
    timestamp = build.get("timestamp", 0)

    start_time = datetime.utcfromtimestamp(timestamp / 1000)
    end_time = datetime.utcfromtimestamp((timestamp + duration) / 1000)

    json_body = [
        {
            "measurement": MEASUREMENT,
            "tags": {
                "project": job_name,
                "view": view,
                "triggered_by_user": causer,
            },
            "time": start_time.isoformat(),
            "fields": {
                "build_number": int(build_number),
                "build_result": str(result),
                "duration_ms": int(duration),
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
            },
        }
    ]

    client.write_points(json_body)
    print(f"[INFO] Written to Influx: {job_name} #{build_number} ({view})")


# -----------------------------
# Main
# -----------------------------
def main():
    views = get_json(f"{JENKINS_URL}/api/json?tree=views[name,jobs[name]]")
    if not views:
        sys.exit(1)

    for v in views.get("views", []):
        view_name = v["name"]

        # 🚫 Skip All and Monitoring views
        if view_name.lower() in ["all", "monitoring"]:
            continue

        for job in v.get("jobs", []):
            job_name = job["name"]
            builds = get_json(f"{JENKINS_URL}/job/{job_name}/api/json?tree=builds[number,timestamp,duration,result,actions[causes[userName]]]")
            if not builds:
                continue

            for b in builds.get("builds", []):
                num = b["number"]

                # Get detailed build info for causer
                build_details = get_json(f"{JENKINS_URL}/job/{job_name}/{num}/api/json")
                if not build_details:
                    continue
                causer = get_causer(build_details)

                if not already_in_influx(job_name, num, view_name):
                    write_to_influx(job_name, b, view_name, causer)


if __name__ == "__main__":
    main()
