import os
import time
import json
import threading
import traceback

import requests
from flask import Flask, Response, request, render_template

from config import (
    ATTRIBUTES_URL,
    CONTROL_URL,
    THINGS_ACCESS_TOKEN,
    SCRAPE_INTERVAL,
    SETTABLE_FIELDS,
    LATEST_DATA_FILE
)


app = Flask(__name__)
app.json.ensure_ascii = False

latest_current_data = {}
latest_simple_data = []
latest_update_time = ""
latest_error = ""
latest_count = 0

data_lock = threading.Lock()

worker_started = False
worker_lock = threading.Lock()


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


def json_response(data):
    return Response(
        json.dumps(data, ensure_ascii=False, indent=2),
        content_type="application/json; charset=utf-8"
    )


def get_headers():
    if not THINGS_ACCESS_TOKEN:
        raise ValueError("请先在 Render 环境变量里填写 THINGS_ACCESS_TOKEN")

    return {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json;charset=UTF-8",
        "origin": "https://console.thingscloud.xyz",
        "referer": "https://console.thingscloud.xyz/",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "x-access-token": THINGS_ACCESS_TOKEN,
        "x-timezone": "Asia/Shanghai",
        "cache-control": "no-cache",
        "pragma": "no-cache"
    }


def get_settable_type(identifier, value=None, attr_type=None, data_type=None):
    if identifier in SETTABLE_FIELDS:
        return SETTABLE_FIELDS[identifier]

    if attr_type in ["push", "share"]:
        if data_type == "boolean":
            return "boolean"

        if data_type == "number":
            return "number"

    if identifier.startswith("PowerSwitch"):
        return "boolean"

    if identifier.endswith("_setting"):
        return "number"

    if isinstance(value, bool):
        return "boolean"

    return None


def is_settable(identifier, value=None):
    return get_settable_type(identifier, value) is not None


def format_value(value, data_type, model):
    if data_type == "boolean":
        options = model.get("data_options", {}) if isinstance(model, dict) else {}
        on_text = options.get("on_text", "ON")
        off_text = options.get("off_text", "OFF")
        return on_text if value else off_text

    if value is None:
        return ""

    return str(value)


def format_update_time(time_diff):
    if not time_diff:
        return ""

    text = str(time_diff)

    if text.endswith("更新"):
        return text

    return text + "更新"


def scrape_thingscloud_data():
    """
    直接请求 ThingsCloud 当前属性接口。
    """
    headers = get_headers()

    response = requests.get(
        ATTRIBUTES_URL,
        headers=headers,
        timeout=15
    )

    print("读取 ThingsCloud 状态码:", response.status_code)

    if response.status_code != 200:
        raise RuntimeError(
            f"读取 ThingsCloud 失败，状态码：{response.status_code}，内容：{response.text}"
        )

    result_json = response.json()

    if result_json.get("result") is not True:
        raise RuntimeError(f"ThingsCloud 返回失败：{result_json}")

    info_list = result_json.get("info", [])

    if not isinstance(info_list, list):
        raise RuntimeError(
            f"ThingsCloud 返回格式异常：info 不是列表，实际为：{type(info_list)}"
        )

    result = {}

    for item in info_list:
        identifier = item.get("identifier")
        raw_value = item.get("value")
        attr_type = item.get("attr_type")
        attr_type_text = item.get("attr_type_text")
        data_type = item.get("data_type")
        time_diff = item.get("time_diff")
        model = item.get("model", {}) or {}

        if not identifier:
            continue

        name = model.get("name", identifier)
        data_options = model.get("data_options", {}) or {}
        unit = data_options.get("unit", "")

        field_type = get_settable_type(
            identifier=identifier,
            value=raw_value,
            attr_type=attr_type,
            data_type=data_type
        )

        display_value = format_value(raw_value, data_type, model)

        result[identifier] = {
            "title": f"{name} ({identifier})",
            "name": name,
            "identifier": identifier,
            "value": display_value,
            "raw_value": raw_value,
            "unit": unit,
            "update_time": format_update_time(time_diff),
            "attr_type": attr_type,
            "attr_type_text": attr_type_text,
            "data_type": data_type,
            "can_set": field_type is not None,
            "field_type": field_type
        }

    return result


def convert_to_simple_list(current_data):
    items = []

    for identifier, item in current_data.items():
        items.append({
            "name": item.get("name", ""),
            "identifier": identifier,
            "value": item.get("value", ""),
            "raw_value": item.get("raw_value"),
            "unit": item.get("unit", ""),
            "update_time": item.get("update_time", ""),
            "attr_type": item.get("attr_type", ""),
            "attr_type_text": item.get("attr_type_text", ""),
            "data_type": item.get("data_type", ""),
            "can_set": item.get("can_set", False),
            "field_type": item.get("field_type", None)
        })

    return items


def save_latest_data_to_file():
    """
    保存最新数据。
    Render 免费服务的文件系统可能会重启后丢失，但运行期间可用于调试。
    """
    with data_lock:
        file_data = {
            "success": True,
            "update_time": latest_update_time,
            "error": latest_error,
            "count": latest_count,
            "data": latest_simple_data
        }

    try:
        with open(LATEST_DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(file_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("保存 latest_data.json 失败：", e)


def convert_set_value(identifier, value):
    field_type = get_settable_type(identifier, value)

    if field_type is None:
        raise ValueError(f"{identifier} 不是可下发属性")

    if field_type == "boolean":
        if isinstance(value, bool):
            return value

        value_str = str(value).strip().lower()

        if value_str in ["true", "1", "on", "open", "开", "打开"]:
            return True

        if value_str in ["false", "0", "off", "close", "关", "关闭"]:
            return False

        raise ValueError("布尔值只能是 true/false、ON/OFF、1/0、打开/关闭")

    if field_type == "number":
        value_str = str(value).strip()

        if value_str == "":
            raise ValueError("数值不能为空")

        number_value = float(value_str)

        if number_value.is_integer():
            return int(number_value)

        return number_value

    return value


def display_value_for_cache(identifier, real_value):
    field_type = get_settable_type(identifier, real_value)

    if field_type == "boolean":
        return "ON" if real_value else "OFF"

    return str(real_value)


def update_cache_after_set(identifier, real_value):
    global latest_current_data
    global latest_simple_data
    global latest_update_time
    global latest_count

    display_value = display_value_for_cache(identifier, real_value)
    now_time = time.strftime("%Y-%m-%d %H:%M:%S")

    with data_lock:
        if identifier in latest_current_data:
            latest_current_data[identifier]["value"] = display_value
            latest_current_data[identifier]["raw_value"] = real_value
            latest_current_data[identifier]["update_time"] = "刚刚下发"

        for item in latest_simple_data:
            if item.get("identifier") == identifier:
                item["value"] = display_value
                item["raw_value"] = real_value
                item["update_time"] = "刚刚下发"

        latest_update_time = now_time
        latest_count = len(latest_simple_data)

    save_latest_data_to_file()


def post_to_thingscloud(identifier, real_value):
    payload = {
        identifier: real_value
    }

    headers = get_headers()

    print("准备下发到 ThingsCloud：")
    print("URL:", CONTROL_URL)
    print("Payload:", payload)

    response = requests.post(
        CONTROL_URL,
        headers=headers,
        json=payload,
        timeout=15
    )

    print("ThingsCloud 下发状态码:", response.status_code)
    print("ThingsCloud 下发返回内容:", response.text)

    try:
        result = response.json()
    except Exception:
        result = {
            "raw": response.text
        }

    return response.status_code, result


def auto_scrape_worker():
    global latest_current_data
    global latest_simple_data
    global latest_update_time
    global latest_error
    global latest_count

    while True:
        try:
            print("开始自动读取 ThingsCloud 数据...")

            current_data = scrape_thingscloud_data()
            simple_data = convert_to_simple_list(current_data)
            now_time = time.strftime("%Y-%m-%d %H:%M:%S")

            with data_lock:
                latest_current_data = current_data
                latest_simple_data = simple_data
                latest_update_time = now_time
                latest_error = ""
                latest_count = len(simple_data)

            save_latest_data_to_file()

            print("读取成功：", now_time)
            print("读取数据条数：", len(simple_data))

        except Exception as e:
            now_time = time.strftime("%Y-%m-%d %H:%M:%S")
            error_detail = traceback.format_exc()

            with data_lock:
                latest_error = str(e)
                latest_update_time = now_time

            print("读取失败：", e)
            print(error_detail)

        time.sleep(SCRAPE_INTERVAL)


def start_background_worker_once():
    global worker_started

    with worker_lock:
        if worker_started:
            return

        worker_started = True

        scrape_thread = threading.Thread(
            target=auto_scrape_worker,
            daemon=True
        )
        scrape_thread.start()

        print("后台自动读取线程已启动")


@app.route("/", methods=["GET"])
def index():
    return json_response({
        "success": True,
        "message": "ThingsCloud 云端读取与下发服务已启动",
        "dashboard": "/dashboard",
        "api_simple": "/api/home/simple",
        "api_current": "/api/home/current",
        "api_status": "/api/home/status",
        "api_refresh": "/api/home/refresh",
        "api_set": "/api/home/set",
        "latest_data_file": str(LATEST_DATA_FILE)
    })


@app.route("/dashboard", methods=["GET"])
def dashboard():
    return render_template("dashboard.html")


@app.route("/api/home/simple", methods=["GET"])
def home_simple():
    with data_lock:
        return json_response({
            "success": True,
            "update_time": latest_update_time,
            "error": latest_error,
            "count": latest_count,
            "data": latest_simple_data
        })


@app.route("/api/home/current", methods=["GET"])
def home_current():
    with data_lock:
        return json_response({
            "success": True,
            "update_time": latest_update_time,
            "error": latest_error,
            "count": latest_count,
            "data": latest_current_data
        })


@app.route("/api/home/status", methods=["GET"])
def home_status():
    with data_lock:
        return json_response({
            "success": True,
            "update_time": latest_update_time,
            "error": latest_error,
            "count": latest_count
        })


@app.route("/api/home/refresh", methods=["GET"])
def home_refresh():
    global latest_current_data
    global latest_simple_data
    global latest_update_time
    global latest_error
    global latest_count

    try:
        current_data = scrape_thingscloud_data()
        simple_data = convert_to_simple_list(current_data)
        now_time = time.strftime("%Y-%m-%d %H:%M:%S")

        with data_lock:
            latest_current_data = current_data
            latest_simple_data = simple_data
            latest_update_time = now_time
            latest_error = ""
            latest_count = len(simple_data)

        save_latest_data_to_file()

        return json_response({
            "success": True,
            "message": "手动刷新成功",
            "update_time": now_time,
            "count": len(simple_data),
            "data": simple_data
        })

    except Exception as e:
        error_detail = traceback.format_exc()

        with data_lock:
            latest_error = str(e)

        print("手动刷新异常详情：")
        print(error_detail)

        return json_response({
            "success": False,
            "message": "手动刷新失败",
            "error": str(e),
            "trace": error_detail
        })


@app.route("/api/home/set", methods=["POST"])
def home_set():
    try:
        body = request.get_json(force=True)

        print("网页传来的下发请求:", body)

        identifier = body.get("identifier")
        value = body.get("value")

        if not identifier:
            return json_response({
                "success": False,
                "message": "identifier 不能为空"
            })

        if not is_settable(identifier, value):
            return json_response({
                "success": False,
                "message": f"{identifier} 不是可下发属性"
            })

        real_value = convert_set_value(identifier, value)

        print("转换后的下发值:", identifier, real_value)

        status_code, thingscloud_result = post_to_thingscloud(
            identifier,
            real_value
        )

        if status_code != 200:
            return json_response({
                "success": False,
                "message": "ThingsCloud 下发失败",
                "status_code": status_code,
                "result": thingscloud_result
            })

        if thingscloud_result.get("result") is not True:
            return json_response({
                "success": False,
                "message": "ThingsCloud 返回失败",
                "status_code": status_code,
                "result": thingscloud_result
            })

        update_cache_after_set(identifier, real_value)

        return json_response({
            "success": True,
            "message": "下发成功",
            "identifier": identifier,
            "value": real_value,
            "thingscloud_result": thingscloud_result
        })

    except Exception as e:
        error_detail = traceback.format_exc()

        print("下发异常详情：")
        print(error_detail)

        return json_response({
            "success": False,
            "message": "下发异常",
            "error": str(e),
            "trace": error_detail
        })


start_background_worker_once()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False
    )