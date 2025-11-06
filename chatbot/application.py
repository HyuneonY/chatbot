from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO
import sys
from common import model
from chatbot import Chatbot
from characters import system_role, instruction
import atexit
import psycopg2

# PostgreSQL 연결 설정
PG_CONFIG = {
    "dbname": "postgres",
    "user": "postgres",
    "password": "pgadmin1002",
    "host": "192.168.243.24"
}

application = Flask(__name__)
socketio = SocketIO(application, cors_allowed_origins="*")

# jjinchin 인스턴스 생성
jjinchin = Chatbot(
    model=model.basic,
    system_role=system_role,
    instruction=instruction,
    user="사용자",
    assistant="경비"
)


@application.route("/")
def hello():
    return "Hello goorm!"


@application.route("/chat-app")
def chat_app():
    return render_template("chat.html")


@application.route("/chat-api", methods=['POST'])
def chat_api():
    request_message = request.json.get('request_message', '').strip()
    jjinchin.add_user_message(request_message)

    # ✅ “최근 이상현상” 요청일 경우 — DB 조회
    if "최근 이상현상" in request_message:
        latest = jjinchin.get_latest_event()
        if latest:
            guide = {
                "흡연": "금연 구역 내 흡연 시, CCTV 영상과 위치를 관리자에게 전달하세요.",
                "유기물": "방치된 물체나 동물 상태를 확인 후 관리 담당자에게 알리세요.",
                "파손": "현장 접근을 제한하고, 파손된 물체나 시설을 관리자에게 보고하세요.",
                "폭행": "즉시 경보를 울리고, 보안팀과 경찰에 연락하세요.",
                "교통약자": "위험 상황 시 주변 사람에게 도움을 요청하고, 관리자에게 즉시 알리세요.",
                "화재": "불꽃 또는 연기 감지 시 즉시 경보를 울리고 119에 신고하세요."
            }.get(latest["type"], "관리자에게 보고하고 현장을 점검하세요.")

            response_message = (
                "최근 감지된 이상현상입니다.<br>"
                f"- 이름: {latest['camera']}<br>"
                f"- 유형: {latest['type']}<br>"
                f"- 시간: {latest['date']}<br>"
                f"- 경로: {latest['image_path']}<br>"
                f"🔹 해결 방법: {guide}"
            )
        else:
            response_message = "현재 등록된 이상현상이 없습니다."

        jjinchin.add_response(response_message)
        return jsonify({"response_message": response_message})

    # ✅ 일반 질문일 경우 — Chatbot 내부 로직 실행
    response_message = jjinchin.get_response_content()
    jjinchin.add_response(response_message)
    return jsonify({"response_message": response_message})


@atexit.register
def shutdown():
    print("flask shutting down...")
    jjinchin.save_chat()


# 🔹 새 이상현상 콜백 함수
def on_new_event(event_message):
    """새 이상현상 감지 시 클라이언트에게 push"""
    print("🚨 새 이상현상 감지:", event_message)
    socketio.emit('new_event', {'message': event_message})


if __name__ == "__main__":
    # 🔹 백그라운드 모니터링 시작
    jjinchin.start_event_monitor(interval=3, callback=on_new_event)
    socketio.run(application, host='0.0.0.0', port=int(sys.argv[1]), debug=True)
