#!/usr/bin/env python3


import requests
import json
import sys
import os
import urllib.parse
from datetime import datetime
import logging
from requests.auth import HTTPBasicAuth

# =========================
# CONFIGURATION
# =========================
JENKINS_URL = os.getenv('JENKINS_URL', 'http://localhost:8080')
JENKINS_USER = os.getenv('JENKINS_USER', 'namratha_km')
JENKINS_TOKEN = os.getenv('JENKINS_TOKEN', '')

INFLUX_URL = os.getenv('INFLUX_URL', 'http://localhost:8086')
INFLUX_DB = os.getenv('INFLUX_DB', 'jenkins')
MEASUREMENT = os.getenv('MEASUREMENT', 'jenkins_custom_data')

# =========================
# LOGGING SETUP
# =========================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class JenkinsInfluxCollector:
    def __init__(self):
        self.jenkins_url = JENKINS_URL.rstrip('/')
        self.jenkins_user = JENKINS_USER
        self.jenkins_token = JENKINS_TOKEN
        self.influx_url = INFLUX_URL.rstrip('/')
        self.influx_db = INFLUX_DB
        self.measurement = MEASUREMENT
        
        self.auth = HTTPBasicAuth(self.jenkins_user, self.jenkins_token)
        self.session = requests.Session()
        self.session.auth = self.auth
        
        logger.info("=== JENKINS TO INFLUXDB DATA COLLECTOR - project_name as tag ===")
        logger.info(f"Jenkins URL: {self.jenkins_url}")
        logger.info(f"InfluxDB URL: {self.influx_url}")
        logger.info(f"Database: {self.influx_db}")
        logger.info(f"Measurement: {self.measurement}")

    def escape_value(self, value):
        if value is None:
            return ""
        return str(value).replace(' ', '\\ ').replace(',', '\\,').replace('=', '\\=').replace('"', '\\"')

    def escape_influx_query(self, value):
        if value is None:
            return ""
        return str(value).replace("'", "\\'")

    def make_jenkins_request(self, endpoint, timeout=30):
        url = f"{self.jenkins_url}{endpoint}"
        try:
            response = self.session.get(url, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error making request to {url}: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing JSON from {url}: {e}")
            return None

    def make_influx_request(self, endpoint, data=None, method='GET'):
        url = f"{self.influx_url}{endpoint}"
        try:
            if method == 'POST':
                response = requests.post(url, data=data, timeout=10)
            else:
                response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            logger.error(f"Error {method} request to {url}: {e}")
            return None

    def extract_user_details(self, build_details):
        user_info = {
            'triggered_by_user': 'Unknown',
            'user_display_name': 'Unknown', 
            'trigger_type': 'Unknown',
            'trigger_description': 'Unknown',
            'remote_address': '',
            'upstream_project': '',
            'upstream_build': ''
        }
        try:
            actions = build_details.get('actions', [])
            for action in actions:
                if isinstance(action, dict) and 'causes' in action:
                    for cause in action['causes']:
                        cause_class = cause.get('_class', '')
                        if cause_class == 'hudson.model.Cause$UserIdCause':
                            user_info['triggered_by_user'] = cause.get('userId', 'Unknown')
                            user_info['user_display_name'] = cause.get('userName', user_info['triggered_by_user'])
                            user_info['trigger_type'] = 'Manual'
                            user_info['trigger_description'] = f"Manually triggered by {user_info['user_display_name']}"
                            return user_info
                        elif cause_class == 'hudson.triggers.TimerTrigger$TimerTriggerCause':
                            user_info['triggered_by_user'] = 'System-Timer'
                            user_info['user_display_name'] = 'Jenkins Timer'
                            user_info['trigger_type'] = 'Timer'
                            user_info['trigger_description'] = 'Scheduled/Cron trigger'
                            return user_info
                        elif cause_class == 'hudson.triggers.SCMTrigger$SCMTriggerCause':
                            user_info['triggered_by_user'] = 'System-SCM'
                            user_info['user_display_name'] = 'Git/SCM Change'
                            user_info['trigger_type'] = 'SCM'
                            user_info['trigger_description'] = 'Source code change detected'
                            return user_info
                        elif cause_class == 'org.jenkinsci.plugins.workflow.support.steps.build.BuildUpstreamCause':
                            upstream_project = cause.get('upstreamProject', 'Unknown')
                            upstream_build = cause.get('upstreamBuild', '')
                            user_info['triggered_by_user'] = 'System-Upstream'
                            user_info['user_display_name'] = f'Upstream: {upstream_project}'
                            user_info['trigger_type'] = 'Upstream'
                            user_info['trigger_description'] = f'Triggered by upstream job {upstream_project}#{upstream_build}'
                            user_info['upstream_project'] = upstream_project
                            user_info['upstream_build'] = str(upstream_build)
                            return user_info
                        elif cause_class == 'hudson.model.Cause$RemoteCause':
                            remote_addr = cause.get('addr', 'Unknown')
                            user_info['triggered_by_user'] = 'API-Remote'
                            user_info['user_display_name'] = f'Remote API ({remote_addr})'
                            user_info['trigger_type'] = 'Remote-API'
                            user_info['trigger_description'] = f'Remote API call from {remote_addr}'
                            user_info['remote_address'] = remote_addr
                            return user_info
                        elif 'GitHubPushCause' in cause_class:
                            user_info['triggered_by_user'] = 'GitHub-Webhook'
                            user_info['user_display_name'] = 'GitHub Push'
                            user_info['trigger_type'] = 'GitHub'
                            user_info['trigger_description'] = 'GitHub webhook trigger'
                            return user_info
        except Exception as e:
            logger.warning(f"Error extracting user details: {e}")
        return user_info

    def insert_build_to_influx(self, project_name, project_path, view_name, build_data):
        try:
            build_time_ns = build_data['timestamp'] * 1_000_000
            build_time_str = datetime.fromtimestamp(build_data['timestamp']/1000).strftime('%Y-%m-%dT%H:%M:%S.%fZ')

            build_result = build_data.get('result', 'UNKNOWN')
            build_duration = build_data.get('duration', 0)
            build_number = build_data['number']

            user_info = build_data.get('user_info', {})
            triggered_by = user_info.get('triggered_by_user', 'Unknown')
            user_display_name = user_info.get('user_display_name', 'Unknown')
            trigger_type = user_info.get('trigger_type', 'Unknown')
            trigger_description = user_info.get('trigger_description', 'Unknown')

            # Escape values
            escaped_project_name = self.escape_value(project_name)
            escaped_project_path = self.escape_value(project_path)
            escaped_view_name = self.escape_value(view_name)
            escaped_build_result = self.escape_value(build_result)
            escaped_build_time_str = self.escape_value(build_time_str)
            escaped_triggered_by = self.escape_value(triggered_by)
            escaped_user_display_name = self.escape_value(user_display_name)
            escaped_trigger_type = self.escape_value(trigger_type)
            escaped_trigger_description = self.escape_value(trigger_description)

            # --- PROJECT_NAME IS NOW A TAG ---
            payload = (f"{self.measurement},"
                       f"project_name={escaped_project_name},"
                       f"project_path={escaped_project_path},"
                       f"view={escaped_view_name},"
                       f"trigger_type={escaped_trigger_type},"
                       f"triggered_by_user={escaped_triggered_by} "
                       f"build_number={build_number}i,"
                       f"build_duration={build_duration}i,"
                       f"build_result=\"{escaped_build_result}\","
                       f"build_time=\"{escaped_build_time_str}\","
                       f"user_display_name=\"{escaped_user_display_name}\","
                       f"trigger_description=\"{escaped_trigger_description}\" "
                       f"{build_time_ns}")

            response = self.make_influx_request(f"/write?db={self.influx_db}", data=payload, method='POST')

            if response:
                logger.info(f"✅ {project_name} #{build_number} → Triggered by: {user_display_name}")
                return True
            else:
                logger.error(f"❌ Failed to insert {project_name} #{build_number}")
                return False
        except Exception as e:
            logger.error(f"Error inserting build into InfluxDB: {e}")
            return False

    def get_job_builds(self, job_name, job_full_name):
        endpoint = f"/job/{job_name}/api/json?tree=builds[number,timestamp,duration,result,url]"
        job_data = self.make_jenkins_request(endpoint)
        if not job_data:
            return []

        builds = job_data.get('builds', [])
        detailed_builds = []

        for build in builds:
            build_number = build['number']
            build_details = self.make_jenkins_request(f"/job/{job_name}/{build_number}/api/json")
            if build_details:
                user_info = self.extract_user_details(build_details)
                enhanced_build = {
                    'number': build_details.get('number', build['number']),
                    'timestamp': build_details.get('timestamp', build.get('timestamp', 0)),
                    'duration': build_details.get('duration', build.get('duration', 0)),
                    'result': build_details.get('result', build.get('result', 'UNKNOWN')),
                    'url': build_details.get('url', build.get('url', '')),
                    'user_info': user_info
                }
                detailed_builds.append(enhanced_build)
            else:
                build['user_info'] = {
                    'triggered_by_user': 'Unknown',
                    'user_display_name': 'Unknown',
                    'trigger_type': 'Unknown',
                    'trigger_description': 'Failed to get details'
                }
                detailed_builds.append(build)
        return detailed_builds

    def is_build_already_inserted(self, project_name, project_path, view_name, build_number):
        try:
            query = f"SELECT build_number FROM {self.measurement} WHERE project_name='{self.escape_influx_query(project_name)}' " \
                    f"AND project_path='{self.escape_influx_query(project_path)}' " \
                    f"AND view='{self.escape_influx_query(view_name)}' " \
                    f"AND build_number={build_number}"
            encoded_query = urllib.parse.quote(query)
            response = self.make_influx_request(f"/query?db={self.influx_db}&q={encoded_query}")
            if response and response.text:
                return '"series"' in response.text
            return False
        except Exception as e:
            logger.warning(f"Error checking duplicate: {e}")
            return False

    def get_jenkins_views(self):
        jenkins_data = self.make_jenkins_request('/api/json?tree=views[name,url,jobs[name,fullName,url]]')
        if not jenkins_data:
            jenkins_data = self.make_jenkins_request('/api/json')
        if not jenkins_data:
            return []
        views = jenkins_data.get('views', [])
        if not views and jenkins_data.get('jobs'):
            views = [{'name': 'All', 'url': f"{self.jenkins_url}/", 'jobs': jenkins_data['jobs']}]
        return views

    def process_jobs_and_builds(self):
        views = self.get_jenkins_views()
        if not views:
            return False

        total_jobs_processed = 0
        total_builds_processed = 0
        skipped_builds = 0
        user_stats = {}

        for view in views:
            view_name = view['name']
            if view_name.lower() == 'all' and len(views) > 1:
                continue
            jobs = view.get('jobs', [])
            for job in jobs:
                job_name = job['name']
                job_full_name = job.get('fullName', job_name)
                total_jobs_processed += 1
                builds = self.get_job_builds(job_name, job_full_name)
                for build in builds:
                    build_number = build['number']
                    user_info = build.get('user_info', {})
                    triggered_by = user_info.get('triggered_by_user', 'Unknown')
                    if triggered_by in user_stats:
                        user_stats[triggered_by] += 1
                    else:
                        user_stats[triggered_by] = 1
                    if not self.is_build_already_inserted(job_name, job_full_name, view_name, build_number):
                        if self.insert_build_to_influx(job_name, job_full_name, view_name, build):
                            total_builds_processed += 1
                    else:
                        skipped_builds += 1

        logger.info(f"Total jobs processed: {total_jobs_processed}")
        logger.info(f"Total new builds inserted: {total_builds_processed}")
        logger.info(f"Total builds skipped: {skipped_builds}")
        logger.info("=== USER ACTIVITY ===")
        for user, count in sorted(user_stats.items(), key=lambda x: x[1], reverse=True):
            logger.info(f"{user}: {count} builds")
        return total_jobs_processed > 0

    def run(self):
        if not self.jenkins_token:
            logger.error("JENKINS_TOKEN is required")
            return False
        return self.process_jobs_and_builds()


def main():
    collector = JenkinsInfluxCollector()
    success = collector.run()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
