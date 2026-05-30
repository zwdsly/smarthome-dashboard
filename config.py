import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
LATEST_DATA_FILE = BASE_DIR / "latest_data.json"

ATTRIBUTES_URL = "https://sh-3-api.iot-api.com/web/v1/project/2d3545ae-719d-448e-881b-9029453c16f6/device/1f05717d-8f4b-497c-b6fc-6d1426ad0148/attributes"

CONTROL_URL = "https://sh-3-api.iot-api.com/web/v1/project/2d3545ae-719d-448e-881b-9029453c16f6/control/device/q4v8tzk8/attributes"

THINGS_ACCESS_TOKEN = os.environ.get("THINGS_ACCESS_TOKEN", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6InJza21rZngyIiwiZW1haWwiOiIyMDExOTA2NzEyQHFxLmNvbSIsImlhdCI6MTc4MDA2OTc5NCwiZXhwIjoxODExNjA1Nzk0fQ.jcnxd6gowcXMcEXqTYf2yerIUJBoqOkpc_Yds5CzvNk")

SCRAPE_INTERVAL = 10

SETTABLE_FIELDS = {
    "PowerSwitch_1": "boolean",
    "PowerSwitch_2": "boolean",
    "Sunlight_setting": "number",
    "humi_setting": "number",
    "temp_setting": "number",
    "PM25_setting": "number"
}