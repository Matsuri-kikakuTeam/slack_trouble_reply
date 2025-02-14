from sre_constants import error
import logging
import requests
import json
from datetime import datetime

def get_api_token():
    url = 'https://api.m2msystems.cloud/login'
    mail = "development+20211103@matsuri-tech.com"
    password = "rYGOOh9PgUxFhjhd"

    payload = {
        "email": mail,
        "password": password
    }

    try:
        response = requests.post(url, json=payload)
        print("Status code:", response.status_code)
        print("Response text:", response.text)
        if response.status_code == 200:
            json_data = response.json()
            token = json_data.get('accessToken')
            return token
        else:
            return None
    except requests.exceptions.RequestException as e:
        print("Request Exception:", str(e))
        return None



def making_tour(handover_data, action_id):
    try:
        logging.info("hand_over_makingtour 実行開始")

        if not handover_data.get('common_area_id') and not handover_data.get('listing_id'):
            error_message = "commonAreaId または listingId が空です。処理を中止します。"
            logging.error(error_message)
            return {
                "success": "error",
                "cleaner_name": [],
                "response_data": {"error": error_message}
            }

        token = get_api_token()
        if not token:
            logging.error("トークンを取得できませんでした。")
            raise ValueError("トークン取得失敗")

        logging.info(f"取得したトークン: {token}")

        placement = ""
        if handover_data['common_area_id']:
            placement = "commonArea"
        elif handover_data['listing_id']:
            placement = "listing"

        note = "\n".join([
            f"【トラブル分類】\n{handover_data.get('trouble_contents', '')}",
            f"【誰から】\n{handover_data.get('rq_person', '')}",
            f"【何が起きた】\n{handover_data.get('incident', '')}",
            f"【何をしてほしい】\n{handover_data.get('request', '')}",
        ])

        cleaner_name = "未設定"
        cleaner = []

        if action_id == "button_TASK":
            cleaner_name = "TASK"
            cleaner = ["f9afe0ee-424e-4eb8-b294-ae9ff20d4257"]
        elif action_id == "button_CX":
            cleaner_name = "CX"
            cleaner = ["27127fa6-a3ef-41dd-838c-87cb0ebf044f"]
        elif action_id == "button_設備機器":
            cleaner_name = "設備機器"
            cleaner = ["b57eac85-8829-4a71-a0a7-4f6ebd8ade08"]
        elif action_id == "button_SU":    
            cleaner_name = "ASSIGN"
            cleaner = ["b06a4579-13fd-4cda-a4c3-03de3dc66e54"]
        elif action_id == "button_小笠原":
            cleaner_name = "小笠原"
            cleaner = ["91af72ff-d537-4cec-9cc4-2a7d9f20b954"]
        else:
            cleaner_name = "未設定"
            cleaner = []

        admin_url = handover_data.get('admin_url', '')
        if admin_url:
            note = "【このツアーは引き継ぎタスクです。 引継ぎ前のツアーはこちらです】\n" + admin_url + "\n" + note

        # cleaningDate を今日の日付に設定（YYYY-MM-DD形式）
        today_date = datetime.now().strftime('%Y-%m-%d')

        payload = {
            "placement": placement,
            "commonAreaId": handover_data['common_area_id'],
            "listingId": handover_data['listing_id'],
            "cleaningDate": today_date,
            "note": note,
            "cleaners": cleaner,
            "Submission ID": handover_data['Submission ID'],
            "photoTourId": "564605a8-b689-4715-8023-8ff943998c31",
            "handoverId": handover_data.get("handover_id", "")
        }

        print(f"送信ペイロード: {payload}")

        api_url = 'https://api-cleaning.m2msystems.cloud/v3/cleanings/create_with_placement'
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
        response = requests.post(api_url, headers=headers, json=payload)
        logging.info(f"APIレスポンス: {response.status_code}, {response.text}")

        if response.status_code == 200:
            return {
                "success": "ok",
                "cleaner_name": cleaner_name,
                "response_data": response.json()
            }
        else:
            return {
                "success": "error",
                "cleaner_name": cleaner_name,
                "response_data": response.json()
            }

    except Exception as e:
        logging.error(f"エラーが発生しました: {str(e)}")
        return {
            "success": "error",
            "cleaner_name": [],
            "response_data": {"error": str(e)}
        }



##以下、Slackに引き継いだトラブルをSlackのチャンネルのメインストリームに投げる関数

def send_report_to_slack(sent_contents):
    slack_token = "トークン"
    success_results = []  # 各レポートの処理結果を辞書形式で格納

    try:
        for report in sent_contents:  # リスト内の各辞書を処理
            try:
                made_success = report.get('success')
                trouble_contents = report.get('trouble_contents')
                assign = report.get('assign')
                property_name = report.get('property_name', '')

                if made_success == "ok":
                    # 1) メインメッセージをSlackへ送信（最初の移管メッセージ）
                    message_payload = create_message_payload(report, trouble_contents, assign, property_name)
                    main_message_response = send_to_slack(slack_token, message_payload)

                    # 2) メインメッセージの ts を thread_ts として取得
                    thread_ts = main_message_response.get('ts')

                    # 3) スレッドURLを作成
                    new_thread_url = f"https://slack.com/archives/{main_message_response['channel']}/p{thread_ts.replace('.', '')}"

                    # 4) 無効化（deactivate）用のメッセージを作成＆送信（同じスレッドに投稿）
                    deactivate_payload = create_takeover_payload(report, thread_ts)
                    send_to_slack(slack_token, deactivate_payload)

                    # 5) 部署選択ボタンのスレッドを投稿
                    team_selection_payload = create_team_selection_payload(report, thread_ts)
                    team_selection_response = send_to_slack(slack_token, team_selection_payload)

                    # 6) 部署選択ボタンが押されてツアー作成
                    # ここでツアー作成を行い、ツアーの情報を取得
                    tour_response = making_tour(report, "button_TASK")  # 例: action_idが "button_TASK" の場合
                    announce_data = report.copy()
                    announce_data["new_thread_url"] = new_thread_url  # スレッドURLを追加
                    announce_data["thread_ts"] = thread_ts  # 最初のスレッドのタイムスタンプを追加
                    announce_data["tour_info"] = tour_response.get("response_data", "ツアー情報が見つかりませんでした")

                    # 7) ツアー作成情報を新しく作成されたスレッドに投稿
                    announce_payload = create_announce_payload(announce_data)
                    send_to_slack(slack_token, announce_payload)  # thread_tsを使用して、元のスレッドに追加投稿

                    # 8) 部署選択スレッドを上書きして新しい情報を投稿
                    # 部署選択ボタンが押されたスレッドに「新しいツアー作成完了！」を投稿
                    update_payload = create_update_announce_payload(announce_data)
                    send_to_slack(slack_token, update_payload)  # 部署選択スレッドを上書き

                elif made_success == "error":
                    error_payload = create_error_payload(report)
                    send_to_slack(slack_token, error_payload)

                success_results.append({"success": made_success})

            except Exception as e:
                print(f"Error processing report: {e}")
                success_results.append({"success": "error"})
                continue

    except Exception as e:
        print(f"Global error: {e}")
        success_results.append({"success": "error"})

    return success_results




def create_message_payload(report, trouble_contents, assign, property_name):
    # None の場合は空文字に置き換える
    route = report.get("route") or ""
    trouble_url = report.get("trouble_url") or ""
    stay_period = f"{format_date(report.get('stay_start'))}~{format_date(report.get('stay_end'))}" or ""
    created_at = convert_iso_to_custom_format(report.get('created_at')) or ""


    color = (
        "#ED1A3D" if trouble_contents in ["自火報トラブル", "物理鍵トラブル", "TTlockトラブル"]
        else "#f2c744" if assign == "CX"
        else "#00FF00" if assign == "設備機器"
        else "#FFA500" if assign == "ASSIGN"
        else "#0000ff"
    )

    user1 = "<!subteam^S07PPNZCB6V>"  # cs-tokyo
    user2 = "<!subteam^S05NVPXMSNP>"  # task
    user3 = "<!subteam^S07LRFPBQH2>"  # 設備機器
    user4 = "<!subteam^SFDUBF1CM>"    # SU

    return {
        "channel": "C07AHJ1T17E",
        "text": user1 if assign == "CX" else user3 if assign == "設備機器" else user4 if assign == "ASSIGN" else user2,
        "attachments": [
            {
                "color": color,
                "blocks": [
                    {
                        "type": "header",
                        "text": {"type": "plain_text", "text": "❗️トラブル報告❗️", "emoji": True}
                    },
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": "*分類:*\n" + (trouble_contents or "")}
                    },
                    {
                        "type": "section",
                        "fields": [
                            {"type": "mrkdwn", "text": "*物件名:*\n" + (property_name or "")},
                            {"type": "mrkdwn", "text": "*都道府県:*\n" + (report.get("prefecture") or "")},
                            {"type": "mrkdwn", "text": "*契約属性:*\n" + (report.get("contract_type") or "")},
                            {"type": "mrkdwn", "text": "*OPENステータス:*\n" + (report.get("open_status") or "")},
                            {"type": "mrkdwn", "text": "*フォームID:*\n" + (report.get("Submission ID") or "")}
                        ]
                    },
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": f"*誰から（予約コード）:*\n{report.get('rq_person') or ''}"}
                    },
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": f"*何が起きた:*\n{report.get('incident') or ''}"}
                    },
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": f"*何をして欲しい:*\n{report.get('request') or ''}"}
                    },
                    {
                        "type": "section",
                        "fields": [
                            {"type": "mrkdwn", "text": f"*予約経路:*\n{route}"},
                            {"type": "mrkdwn", "text": f"*滞在期間:*\n{stay_period}"},
                            {"type": "mrkdwn", "text": f"*入力日時:*\n{created_at}"},
                            {"type": "mrkdwn", "text": f"*入力者:*\n{report.get('input_by') or ''}"},
                            {"type": "mrkdwn", "text": f"*入力者所属会社:*\n{report.get('company') or ''}"},
                            {"type": "mrkdwn", "text": f"*トラブルURL:*\n{trouble_url}"},
                            {"type": "mrkdwn", "text": f"*引き継ぎフォームID:*\n{report.get('handover_id') or ''}"}
                        ]
                    },
                    {
                        "type": "section",
                        "fields": [
                            {"type": "mrkdwn", "text": f"*m2m_管理者画面URL:*\n{report.get('new_admin_url')}"},
                            {"type": "mrkdwn", "text": f"*m2m_cleaner画面URL:*\n{report.get('new_cleaner_url')}"}
                        ]
                    }
                ]
            }
        ]
    }


def create_error_payload(report):
    stay_period = f"{format_date(report.get('stay_start'))}~{format_date(report.get('stay_end'))}"
    created_at = convert_iso_to_custom_format(report.get('created_at'))

    return {
        "channel": "C07AHJ1T17E",  # Replace with the actual channel ID or name
        "text" : "<!subteam^S05NVPXMSNP>",
        "attachments": [
            {
                "color": "#000000",
                "blocks": [
                    {
                        "type": "header",
                        "text": {"type": "plain_text", "text": "☠️ツアー作成失敗☠️", "emoji": True}
                    },
                    {
                        "type": "section",
                        "fields": [
                            {"type": "mrkdwn", "text": f"*物件名:*\n{report.get('property_name')}"},
                            {"type": "mrkdwn", "text": f"*都道府県:*\n{report.get('prefecture')}"},
                            {"type": "mrkdwn", "text": f"*契約属性:*\n{report.get('contract_type')}"},
                            {"type": "mrkdwn", "text": f"*OPENステータス:*\n{report.get('open_status')}"},
                            {"type": "mrkdwn", "text": f"*分類:*\n{report.get('trouble_contents')}"},
                            {"type": "mrkdwn", "text": f"*フォームID:*\n{report.get('Submission ID')}"}
                        ]
                    },
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": f"*誰から（予約コード）:*\n{report.get('rq_person')}"}
                    },
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": f"*何が起きた:*\n{report.get('incident')}"}
                    },
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": f"*何をして欲しい:*\n{report.get('request')}"}
                    },
                    {
                        "type": "section",
                        "fields": [
                            {"type": "mrkdwn", "text": f"*予約経路:*\n{report.get('route')}"},
                            {"type": "mrkdwn", "text": f"*滞在期間:*\n{stay_period}"},
                            {"type": "mrkdwn", "text": f"*入力日時:*\n{created_at}"},
                            {"type": "mrkdwn", "text": f"*入力者:*\n{report.get('input_by')}"},
                            {"type": "mrkdwn", "text": f"*入力者所属会社:*\n{report.get('company')}"},
                            {"type": "mrkdwn", "text": f"*トラブルURL:*\n{report.get('trouble_url')}"},
                            {"type": "mrkdwn", "text": f"*引き継ぎフォームID:*\n{report.get('handover_id')}"},

                        ]
                    },
                   {
                        "type": "section",
                        "fields": [
                            {"type": "mrkdwn", "text": f"*m2m_管理者画面URL:*\n{report.get('new_admin_url')}"},
                            {"type": "mrkdwn", "text": f"*m2m_cleaner画面URL:*\n{report.get('new_cleaner_url')}"}
                        ]
                    }
                ]
            }
        ]
    }

def create_takeover_payload(report, thread_ts):
    return {
        "channel": "C07AHJ1T17E",
        "text": "他部署に移管が必要ですか？",
        "thread_ts": thread_ts,
        "attachments": [
            {
                "blocks": [
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": "移管する", "emoji": True},
                                "style": "primary",
                                "action_id": "button_transfer",
                                "value": json.dumps(report, ensure_ascii=False)
                            }
                        ]
                    }
                ]
            }
        ]
    }



def update_slack_message(channel, ts, new_text):
    url = "https://slack.com/api/chat.update"
    headers = {
        "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "channel": channel,
        "ts": ts,
        "text": new_text,
        "attachments": []
    }
    resp = requests.post(url, headers=headers, json=payload)
    resp_data = resp.json()
    print("update_slack_message response:", resp_data)
    return resp_data

def send_to_slack(token, payload):
    url = "https://slack.com/api/chat.postMessage"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    # 送信するペイロードに `thread_ts` を含めることで、スレッドに追加
    response = requests.post(url, json=payload, headers=headers)
    response_data = response.json()
    
    print("Slack API Response:", response_data)
    if not response_data.get("ok"):
        print("Slack API Error:", response_data.get("error"), "- Payload:", payload)
        raise Exception("Slack API Error: " + response_data.get("error"))
    
    return response_data


def format_date(date):
    if not date:
        return "N/A"  # 値が存在しない場合のデフォルト値
    if isinstance(date, str):
        return date
    try:
        return date.strftime('%Y-%m-%d')
    except AttributeError:
        return "N/A"  # None やその他の無効値を処理


def convert_iso_to_custom_format(iso_string):
    if not iso_string:
        return "N/A"  # 値が存在しない場合のデフォルト値
    try:
        # ISO 8601フォーマットの場合
        date = datetime.fromisoformat(iso_string)
    except ValueError:
        try:
            # "YYYY-MM-DD HH:MM:SS" フォーマットの場合
            date = datetime.strptime(iso_string, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return "N/A"  # 解析できない場合のデフォルト値
    return date.strftime('%Y/%m/%d %H:%M:%S')


def create_update_announce_payload(announce_data):
    """
    部署選択スレッドの返信を上書きするためのペイロードを作成する関数
    """
    return {
        "channel": "C07AHJ1T17E",  # 適切なチャンネルIDに置き換え
        "text": f"新しいツアー作成完了！ {announce_data.get('new_thread_url')}",
        "thread_ts": announce_data.get('thread_ts'),  # 最初のスレッドのタイムスタンプを指定
        "attachments": [
            {
                "color": "#00FF00",  # 成功を示す緑色
                "blocks": [
                    {
                        "type": "header",
                        "text": {"type": "plain_text", "text": "新しいツアー作成完了！", "emoji": True}
                    },
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": f"*ツアー情報:*\n{announce_data.get('tour_info', '情報がありません')}"}
                    }
                ]
            }
        ]
    }
