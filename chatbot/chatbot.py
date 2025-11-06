from common import client, makeup_response, gpt_num_tokens
import math
from memory_manager import MemoryManager
import psycopg2
import threading
import time


class Chatbot:
    def __init__(self, model, system_role, instruction, **kwargs):
        self.context = [{"role": "system", "content": system_role}]
        self.model = model
        self.instruction = instruction
        self.max_token_size = 16 * 1024
        self.user = kwargs["user"]
        self.assistant = kwargs["assistant"]
        self.memoryManager = MemoryManager()
        self.context.extend(self.memoryManager.restore_chat())

        # PostgreSQL 연결
        self.pg_conn = psycopg2.connect(
            dbname="postgres",
            user="postgres",
            password="pgadmin1002",
            host="192.168.243.24"
        )
        self._monitor_running = False  # 중복 모니터링 방지 플래그

    # ======================
    # 기본 메시지 처리
    # ======================
    def add_user_message(self, user_message):
        self.context.append({"role": "user", "content": user_message, "saved": False})

    def add_response(self, response):
        if isinstance(response, str):
            self.context.append({"role": "assistant", "content": response})
        elif isinstance(response, dict):
            try:
                content = response['choices'][0]['message']["content"]
                role = response['choices'][0]['message'].get("role", "assistant")
                self.context.append({"role": role, "content": content})
            except Exception:
                self.context.append({"role": "assistant", "content": str(response)})
        else:
            self.context.append({"role": "assistant", "content": str(response)})

    # ======================
    # OpenAI API 요청
    # ======================
    def to_openai_context(self):
        return [{"role": v["role"], "content": v["content"]} for v in self.context]

    def _send_request(self):
        try:
            context = self.to_openai_context()
            if gpt_num_tokens(context) > self.max_token_size:
                self.context.pop()
                return makeup_response("메시지 조금 짧게 보내줄래?")
            response = client.chat.completions.create(
                model=self.model,
                messages=context,
                temperature=0.5,
                top_p=1,
                max_tokens=256
            ).model_dump()
            return response
        except Exception as e:
            print(f"Exception 오류({type(e)}): {e}")
            return makeup_response("[챗봇에 문제가 발생했습니다. 잠시 뒤 이용해주세요]")

    def send_request(self):
        self.context[-1]['content'] += self.instruction
        return self._send_request()

    # ======================
    # PostgreSQL 연동
    # ======================
    def get_camera_count(self):
        try:
            with self.pg_conn.cursor() as cur:
                cur.execute('SELECT COUNT(*) FROM camera_details;')
                result = cur.fetchone()
                return int(result[0]) if result else 0
        except Exception as e:
            print("Error in get_camera_count:", e)
            return 0

    def get_camera_list(self):
        try:
            with self.pg_conn.cursor() as cur:
                cur.execute('SELECT "CameraName" FROM camera_details;')
                rows = cur.fetchall()
                return [r[0] for r in rows] if rows else []
        except Exception as e:
            print("Error in get_camera_list:", e)
            return []

    def get_abnormal_events(self):
        """최근 이상현상 5개 (해결방안 없음)"""
        try:
            with self.pg_conn.cursor() as cur:
                cur.execute(
                    'SELECT camera, type, date, image_path '
                    'FROM incidents ORDER BY incidents_id DESC LIMIT 5;'
                )
                rows = cur.fetchall()
                if not rows:
                    return []
                return [f"{r[0]} ({r[1]}) <br>- 시간: {r[2]},<br>이미지 경로: {r[3]}" for r in rows]
        except Exception as e:
            print("Error in get_abnormal_events:", e)
            return []

    def get_latest_event(self):
        try:
            with self.pg_conn.cursor() as cur:
                cur.execute(
                    'SELECT camera, type, date, image_path '
                    'FROM incidents ORDER BY incidents_id DESC LIMIT 1;'
                )
                row = cur.fetchone()
                if not row:
                    return None
                return {"camera": row[0], "type": row[1], "date": row[2], "image_path": row[3]}
        except Exception as e:
            print("Error in get_latest_event:", e)
            return None

    def get_latest_event_id(self):
        try:
            with self.pg_conn.cursor() as cur:
                cur.execute('SELECT incidents_id FROM incidents ORDER BY incidents_id DESC LIMIT 1;')
                row = cur.fetchone()
                return row[0] if row else 0
        except Exception as e:
            print("Error in get_latest_event_id:", e)
            return 0

    # ======================
    # 챗봇 응답 로직
    # ======================
    def get_response_content(self):
        last_message = self.context[-1]["content"].split("instruction:")[0].strip()

        # 카메라 관련
        if any(k in last_message for k in ["카메라 개수", "카메라 대수", "카메라 몇 대", "카메라 몇개", "카메라 개수"]):
            count = self.get_camera_count()
            response = f"현재 설치된 카메라는 총 {count}대입니다."
            self.add_response(response)
            return response
        if any(k in last_message for k in ["카메라 이름", "카메라 목록"]):
            cameras = self.get_camera_list()
            response = (
                "설치된 카메라 목록: " + ", ".join(cameras)
                if cameras else "설치된 카메라가 없습니다."
            )
            self.add_response(response)
            return response

        # 이상현상 관련
        if any(k in last_message for k in ["이상", "사고", "문제", "고장", "이벤트", "이슈"]):
            if any(k in last_message for k in ["최근", "하나", "한 개", "1개", "마지막"]):
                latest = self.get_latest_event()
                if not latest:
                    response = "현재 등록된 이상현상이 없습니다."
                else:
                    # 영어 → 한글 매핑
                    type_map = {
                        "Smoking": "흡연",
                        "Abandoned Item": "유기",
                        "Damage": "파손",
                        "Violence": "폭행",
                        "Weak User": "교통약자",
                        "Fire": "방화"
                    }

                    # 대응 가이드
                    guide_map = {
                        "흡연": "흡연자 정보를 관리자에게 전달하세요.",
                        "유기": "방치된 물체를 확인 후 담당자에게 알리세요.",
                        "파손": "현장 접근 제한 후 관리자에게 보고하세요.",
                        "폭행": "보안팀과 경찰에 즉시 연락하세요.",
                        "교통약자": "도움이 필요하면 주변에 지원을 요청하세요.",
                        "방화": "즉시 경보를 울리고 119 신고하세요."
                    }

                    # 영어 type → 한글 변환
                    type_kor = type_map.get(latest["type"], latest["type"])
                    guide = guide_map.get(type_kor, "관리자에게 보고하고 현장을 점검하세요.")

                    response = (
                        "최근 감지된 이상현상입니다.<br>"
                        f"- 이름: {latest['camera']}<br>"
                        f"- 유형: {type_kor}<br>"
                        f"- 시간: {latest['date']}<br>"
                        f"- 이미지 경로: {latest['image_path']}<br>"
                        f"🔹 해결 방법: {guide}"
                    )
            else:
                events = self.get_abnormal_events()
                response = (
                    "현재 등록된 이상현상이 없습니다." if not events
                    else "최근 이상현상 목록입니다:<br>" + "<br>".join(f"- {e}" for e in events)
                )
            self.add_response(response)
            return response

        # 일반 질문
        response = self.send_request()
        content = response.get('choices', [{}])[0].get('message', {}).get('content', str(response))
        self.add_response(content)
        return content

    # ======================
    # 유틸
    # ======================
    def save_chat(self):
        self.memoryManager.save_chat(self.context)

    def close_connection(self):
        try:
            if self.pg_conn:
                self.pg_conn.close()
        except Exception as e:
            print("DB 연결 종료 중 오류:", e)

    # ======================
    # 이상현상 실시간 모니터링
    # ======================
    def start_event_monitor(self, interval=3, callback=None):
        """DB에서 새로운 이상현상을 주기적으로 확인하고, 감지 시 자동으로 채팅 생성"""
        self.last_event_id = self.get_latest_event_id()

        def monitor():
            print("[이상현상 모니터링 시작]")
            while True:
                try:
                    latest_id = self.get_latest_event_id()
                    if latest_id and latest_id > self.last_event_id:
                        self.last_event_id = latest_id
                        latest_event = self.get_latest_event()

                        if latest_event:
                            camera = latest_event["camera"]
                            type_ = latest_event["type"]
                            date = latest_event["date"]
                            image_path = latest_event["image_path"]

                            print(f"[새 이상현상 감지] {camera} ({type_}) / {date}")

                            # ✅ 마치 사용자가 '최근 이상현상' 입력한 것처럼 처리
                            trigger_message = "최근 이상현상"
                            self.add_user_message(trigger_message)
                            response = self.get_response_content()
                            self.add_response(response)

                            # ✅ Flask에 콜백 전달
                            if callback:
                                callback(response)

                    time.sleep(interval)

                except Exception as e:
                    print("[이상현상 모니터링 오류]", e)
                    time.sleep(interval)

        threading.Thread(target=monitor, daemon=True).start()

    def stop_event_monitor(self):
        self._monitor_running = False
        print("[이상현상 모니터링 중단]")
