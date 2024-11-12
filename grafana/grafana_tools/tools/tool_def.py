from . import filter_alert

import inspect

from kubiya_sdk import tool_registry
from kubiya_sdk.tools.models import Arg, Tool, FileSpec

analyze_grafana_panel = Tool(
    name="analyze_grafana_panel",
    description="Generate render URLs for relevant Grafana dashboard panels, download images, analyze them using OpenAI's vision model, and send results to the current Slack thread",
    type="docker",
    image="python:3.12",
    content="""
pip install slack_sdk argparse requests litellm==1.49.5 pillow==11.0.0 tempfile > /dev/null 2>&1

python /tmp/grafana.py \
    --grafana_dashboard_url "$grafana_dashboard_url" \
    --alert_name "$alert_name" \
    --alert_severity "$alert_severity" \
    --alert_service_name "$alert_service_name" \
    --alert_reason "$alert_reason" \
    --alert_message "$alert_message" \
    --alert_requests_per_second "$alert_requests_per_second" \
    --alert_active_connections "$alert_active_connections" \
    --alert_container_logs "$alert_container_logs"
""",
    secrets=[
        "SLACK_API_TOKEN", 
        "GRAFANA_API_KEY", 
        "VISION_LLM_KEY"
    ],
    env=[
        "SLACK_THREAD_TS", 
        "SLACK_CHANNEL_ID",
        "VISION_LLM_BASE_URL"
    ],
    args=[
        Arg(name="grafana_dashboard_url", type="str", description="URL of the Grafana dashboard", required=True),
        Arg(name="alert_name", type="str", description="Name of the alert", required=True),
        Arg(name="alert_severity", type="str", description="Severity of the alert", required=True),
        Arg(name="alert_service_name", type="str", description="Name of the affected service", required=True),
        Arg(name="alert_reason", type="str", description="Reason for the alert", required=True),
        Arg(name="alert_message", type="str", description="Alert message", required=True),
        Arg(name="alert_requests_per_second", type="int", description="Number of requests per second", required=True),
        Arg(name="alert_active_connections", type="int", description="Number of active connections", required=True),
        Arg(name="alert_container_logs", type="str", description="Relevant container logs", required=True)
    ],
    with_files=[
        FileSpec(
            destination="/tmp/grafana.py",
            content=inspect.getsource(filter_alert),
        )
    ]
)

# analyze_grafana_panel = Tool(
#     name="analyze_grafana_panel",
#     description="Generate render URLs for relevant Grafana dashboard panels, download images, analyze them using OpenAI's vision model, and send results to the current Slack thread",
#     type="docker",
#     image="python:3.12",
#     content="""
# pip install slack_sdk requests==2.32.3 litellm==1.49.5 pillow==11.0.0 > /dev/null 2>&1

# export GRAFANA_DASHBOARD_URL="$grafana_dashboard_url"
# export ALERT_SUBJECT="$alert_subject"

# curl -o /tmp/grafana.py https://analyze-panel-grafana.s3.eu-west-1.amazonaws.com/filter_alert.py

# python /tmp/grafana.py --grafana_dashboard_url "$grafana_dashboard_url" --alert_subject "$alert_subject"
# """,
#     secrets=[
#         "SLACK_API_TOKEN", 
#         "GRAFANA_API_KEY", 
#         "VISION_LLM_KEY"
#     ],
#     env=[
#         "SLACK_THREAD_TS", 
#         "SLACK_CHANNEL_ID",
#         "VISION_LLM_BASE_URL"
#     ],
#     args=[
#         Arg(
#             name="grafana_dashboard_url",
#             type="str",
#             description="URL of the Grafana dashboard",
#             required=True
#         ),
#         Arg(
#             name="alert_subject",
#             type="str",
#             description="Subject of the alert, used to filter relevant panels",
#             required=True
#         )
#     ]
# )


# Register the updated tool
tool_registry.register("grafana", analyze_grafana_panel)