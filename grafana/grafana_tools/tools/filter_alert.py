import os
import re
import requests
import argparse
import tempfile
from urllib.parse import urlparse, parse_qs
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import json
from litellm import completion
import base64
from PIL import Image
from typing import Dict, List, Tuple, Optional
import logging

# Constants
DEFAULT_ORG_ID = "1"
IMAGE_WIDTH = 1000
IMAGE_HEIGHT = 500
TIME_RANGE = "1h"

# Add at the top of the file
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def generate_grafana_api_url(grafana_dashboard_url: str) -> Tuple[str, str]:
    parsed_url = urlparse(grafana_dashboard_url)
    path_parts = parsed_url.path.strip("/").split("/")

    if len(path_parts) >= 3 and path_parts[0] == "d":
        dashboard_uid = path_parts[1]
    else:
        raise ValueError("URL path does not have the expected format /d/{uid}/{slug}")

    query_params = parse_qs(parsed_url.query)
    org_id = query_params.get("orgId", [DEFAULT_ORG_ID])[0]

    api_url = f"{parsed_url.scheme}://{parsed_url.netloc}/api/dashboards/uid/{dashboard_uid}"
    return api_url, org_id

def get_dashboard_panels(api_url, api_key):
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        response = requests.get(api_url, headers=headers)
        response.raise_for_status()  # Raises an HTTPError for bad responses
        dashboard_data = response.json()
        panels = dashboard_data.get('dashboard', {}).get('panels', [])
        if not panels:
            raise ValueError("No panels found in dashboard")
        return [(panel.get('title'), panel.get('id')) for panel in panels if 'title' in panel and 'id' in panel]
    except requests.exceptions.RequestException as e:
        raise Exception(f"Failed to fetch dashboard data: {str(e)}")

def generate_grafana_render_url(grafana_dashboard_url, panel_id):
    parsed_url = urlparse(grafana_dashboard_url)
    path_parts = parsed_url.path.strip("/").split("/")

    if len(path_parts) >= 3 and path_parts[0] == "d":
        dashboard_uid = path_parts[1]
        dashboard_slug = path_parts[2]
    else:
        raise ValueError("URL path does not have the expected format /d/{uid}/{slug}")

    query_params = parse_qs(parsed_url.query)
    org_id = query_params.get("orgId", ["1"])[0]

    render_url = f"{parsed_url.scheme}://{parsed_url.netloc}/render/d-solo/{dashboard_uid}/{dashboard_slug}?orgId={org_id}&from=now-1h&to=now&panelId={panel_id}&width=1000&height=500"
    return render_url, org_id

def download_panel_image(render_url: str, api_key: str, panel_title: str) -> Optional[bytes]:
    with requests.get(render_url, headers={"Authorization": f"Bearer {api_key}"}, stream=True) as response:
        try:
            response.raise_for_status()
            return response.content
        except requests.exceptions.RequestException as e:
            print(f"Failed to download panel image {panel_title}: {str(e)}")
            return None

def send_slack_file_to_thread(token, channel_id, thread_ts, file_path, initial_comment):
    client = WebClient(token=token)
    try:
        response = client.files_upload_v2(
            channel=channel_id,
            file=file_path,
            initial_comment=initial_comment,
            thread_ts=thread_ts
        )
        return response
    except SlackApiError as e:
        raise

def extract_slack_response_info(response):
    return {
        "ok": response.get("ok"),
        "file_id": response.get("file", {}).get("id"),
        "file_name": response.get("file", {}).get("name"),
        "file_url": response.get("file", {}).get("url_private"),
        "timestamp": response.get("file", {}).get("timestamp")
    }

def analyze_image_with_vision_model(
    image_content: bytes,
    panel_title: str,
    alert_info: Dict[str, str]
) -> str:
    llm_key = os.environ["VISION_LLM_KEY"]
    llm_base_url = os.environ["VISION_LLM_BASE_URL"]

    base64_image = base64.b64encode(image_content).decode('utf-8')

    prompt = f"""Analyze this Grafana panel image titled '{panel_title}' in the context of the following alert:

Alert Name: {alert_info['name']}
Severity: {alert_info['severity']}
Service Name: {alert_info['service_name']}
Reason: {alert_info['reason']}
Message: {alert_info['message']}
Requests per second: {alert_info['requests_per_second']}
Active connections: {alert_info['active_connections']}

1. Does this panel show any significant activity or anomalies that could be related to the alert?
2. Are there any visible spikes, dips, or unusual patterns in the metrics shown?
3. Does the data in this panel correlate with the information provided in the alert?

Respond with 'Relevant' or 'Not Relevant' and provide a brief explanation of your decision."""

    try:
        response = completion(
            model="openai/gpt-4o",
            api_key=llm_key,
            base_url=llm_base_url,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{base64_image}"
                            },
                        },
                    ],
                }
            ],
        )
        return response.choices[0].message.content
    except Exception as e:
        return "Error: Unable to analyze the image"

def find_related_panels(panels: List[Tuple[str, int]], alert_info: Dict, grafana_dashboard_url: str, grafana_api_key: str) -> List[Tuple]:
    related_panels = []
    for panel_title, panel_id in panels:
        logger.info(f"Analyzing panel: {panel_title}")
        render_url, _ = generate_grafana_render_url(grafana_dashboard_url, panel_id)
        image_content = download_panel_image(render_url, grafana_api_key, panel_title)
        
        if image_content:
            analysis_result = analyze_image_with_vision_model(image_content, panel_title, alert_info)
            if analysis_result.lower().startswith('relevant'):
                related_panels.append((panel_title, panel_id, image_content, analysis_result))
        else:
            logger.warning(f"Failed to download image for panel: {panel_title}")

    return related_panels

def main():
    required_env_vars = [
        "SLACK_THREAD_TS",
        "SLACK_CHANNEL_ID",
        "SLACK_API_TOKEN",
        "GRAFANA_API_KEY",
        "VISION_LLM_KEY",
        "VISION_LLM_BASE_URL"
    ]
    
    missing_vars = [var for var in required_env_vars if not os.environ.get(var)]
    if missing_vars:
        raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
    
    parser = argparse.ArgumentParser(description="Process Grafana dashboard and alert data.")
    parser.add_argument("--grafana_dashboard_url", required=True, help="URL of the Grafana dashboard")
    parser.add_argument("--alert_name", required=True, help="Name of the alert")
    parser.add_argument("--alert_severity", required=True, help="Severity of the alert")
    parser.add_argument("--alert_service_name", required=True, help="Name of the affected service")
    parser.add_argument("--alert_reason", required=True, help="Reason for the alert")
    parser.add_argument("--alert_message", required=True, help="Alert message")
    parser.add_argument("--alert_requests_per_second", type=int, required=True, help="Number of requests per second")
    parser.add_argument("--alert_active_connections", type=int, required=True, help="Number of active connections")
    parser.add_argument("--alert_container_logs", required=True, help="Relevant container logs")
    args = parser.parse_args()

    grafana_dashboard_url = args.grafana_dashboard_url
    thread_ts = os.environ.get("SLACK_THREAD_TS")
    channel_id = os.environ.get("SLACK_CHANNEL_ID")
    slack_token = os.environ.get("SLACK_API_TOKEN")
    grafana_api_key = os.environ.get("GRAFANA_API_KEY")

    alert_info = {
        "name": args.alert_name,
        "severity": args.alert_severity,
        "service_name": args.alert_service_name,
        "reason": args.alert_reason,
        "message": args.alert_message,
        "requests_per_second": args.alert_requests_per_second,
        "active_connections": args.alert_active_connections,
        "container_logs": args.alert_container_logs
    }

    api_url, org_id = generate_grafana_api_url(grafana_dashboard_url)
    all_panels = get_dashboard_panels(api_url, grafana_api_key)

    related_panels = find_related_panels(all_panels, alert_info, grafana_dashboard_url, grafana_api_key)

    for panel_title, panel_id, image_content, analysis_result in related_panels:
        render_url, _ = generate_grafana_render_url(grafana_dashboard_url, panel_id)

        initial_comment = (f"Grafana panel image: {panel_title}\n"
                         f"From dashboard: {grafana_dashboard_url}\n\n"
                         f"Analysis:\n{analysis_result}")
        
        with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as temp_file:
            temp_file.write(image_content)
            temp_file_path = temp_file.name

        slack_response = send_slack_file_to_thread(slack_token, channel_id, thread_ts, temp_file_path, initial_comment)

        response_info = extract_slack_response_info(slack_response)

        os.remove(temp_file_path)

if __name__ == "__main__":
    main()
