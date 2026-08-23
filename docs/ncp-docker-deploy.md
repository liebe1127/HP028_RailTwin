# 네이버클라우드(NCP)에 RailTwin FastAPI를 Docker로 올리는 가이드
# ESP32-C3는 `/ws/sensor`, Godot·웹은 `/ws`에 WSS로 접속하는 것이 목표입니다.

## 한눈에 보기

0. (처음이면) **VPC + Public Subnet** 만들기 ← 여기서 가장 많이 막힘
1. Ubuntu 서버 만들기 + **공인 IP**
2. 방화벽(ACG)에서 **22**, **80**, **443** 포트 열기 (HTTP 시연만 할 때는 **8000**)
3. 서버에 Docker 설치 → 코드 받아서 `docker compose up` (HTTPS는 아래 § HTTPS)
4. Godot Inspector의 WebSocket URL을 `wss://hp028-railtwin.duckdns.org/ws` 로 바꾸기

`DEMO_MODE=true`면 가상 센서, `false`면 원격 ESP32-C3 WebSocket 입력만 사용합니다.

> **대신 생성은 불가:** 네이버클라우드 콘솔은 본인 계정·결제·인증키가 필요해서  
> Cursor/AI가 로그인해서 서버를 만들어 줄 수는 없습니다.  
> 아래를 화면 순서대로 따라가면 됩니다. 어디서 빨간 오류/막히면 **화면 문구**를 알려주세요.

---

## 0. 준비물

- 네이버클라우드 플랫폼 계정 + 결제 수단 등록 완료
- 콘솔: https://console.ncloud.com/
- (권장) 서버 스펙: **2 vCPU / 4GB RAM** 이상, OS **Ubuntu 22.04 또는 24.04**

### 콘솔 환경 확인 (중요)

화면 **위쪽**에 `VPC` / `Classic` 전환이 있으면 반드시 **VPC** 를 선택하세요.  
이 가이드는 **VPC 환경** 기준입니다. (Classic 이면 메뉴가 다릅니다.)

---

## 1. VPC와 Public Subnet 만들기 (서버보다 먼저)

서버 생성 화면에 “VPC/Subnet이 없다”고 나오거나 선택이 비면, 이 단계를 안 한 것입니다.

### 1-A. VPC 생성

1. 콘솔 왼쪽 **Services** → **Networking** → **VPC** → **VPC Management**
2. **[VPC 생성]** 클릭
3. 예시 입력 (그대로 써도 됨):
   - VPC 이름: `railtwin-vpc`
   - IP 주소 범위: `172.16.0.0/16`
4. 생성 완료될 때까지 대기 (상태: 운영중)

### 1-B. Subnet 생성 (반드시 Public)

1. 같은 VPC 메뉴에서 **Subnet Management** (서브넷)
2. **[Subnet 생성]** 클릭
3. 예시:
   - Subnet 이름: `railtwin-public`
   - VPC: 방금 만든 `railtwin-vpc`
   - IP 주소 범위: `172.16.1.0/24` (VPC 대역 안의 더 작은 조각)
   - 용도 / Internet Gateway: **Public** (외부 접속·공인 IP용)  
     → Private 로 만들면 나중에 밖에서 SSH/Godot 접속이 안 됩니다.
   - Zone: 기본값(예: KR-2) 그대로 OK
4. 생성 완료 대기

여기까지 되면 서버를 만들 준비가 된 것입니다.

---

## 2. 서버 생성 (Ubuntu)

1. **Services** → **Compute** → **Server** → **Server**
2. **[서버 생성]** 클릭  
   - “콘솔 선택” 팝업이 뜨면 **신규/일반 서버 생성** 쪽으로 진행
3. **서버 이미지**
   - 타입: **OS**
   - 이미지: **Ubuntu** → **22.04** 또는 **24.04** (64-bit) 선택 → 다음
4. **서버 설정** (이름이 조금 달라도 같은 의미끼리 맞추면 됨)
   - 서버 이름: `railtwin-api`
   - VPC: `railtwin-vpc`
   - Subnet: `railtwin-public` (**Public**)
   - 서버 타입: **Standard** 계열, 최소 **2 vCPU / 4GB**  
     (예: `s2-g2` 등 — 화면에서 vCPU·메모리 숫자 보고 고르면 됨)
   - 공인 IP: **할당** / **신규 할당** / **자동 할당** 중 “새로 붙인다”는 옵션 선택  
     (요금이 소액 붙을 수 있음 — 외부에서 Godot 접속하려면 필요)
   - 네트워크 인터페이스: 기본/자동이면 OK
5. **스토리지**: 기본 HDD/SSD **50GB 이하**로 충분 (기본값 OK)
6. **인증키**
   - **새로운 인증키 생성** → 이름 예: `railtwin-key`
   - **.pem 파일 다운로드** → 안전한 폴더에 저장 (**다시 다운로드 불가**)
7. **네트워크 접근 (ACG)**
   - 기존 `default-acg`를 쓰거나 **ACG 생성** 후 선택
   - 생성 직후 규칙이 비어 있으면 다음 절(ACG)에서 **22, 8000**을 꼭 추가
8. 최종 확인 → **서버 생성**
9. 서버 목록에서 상태가 **운영중**이 될 때까지 대기 (수 분)
10. 서버 행에서 **공인 IP** 숫자를 메모 (예: `211.xxx.xxx.xxx`)  
    - 안 보이면: **Services → Compute → Server → Public IP** 에서 할당/연결

공식 문서: [서버 생성 (VPC)](https://guide.ncloud-docs.com/docs/ko/server-create-vpc)

---

## 3. ACG(방화벽)에서 포트 열기

1. **Services** → **Compute** → **Server** → **ACG**
2. 서버에 붙인 ACG 체크 → **[ACG 설정]**
3. **Inbound** 에 규칙 추가:

| 프로토콜 | 접근소스 | 허용포트 | 용도 |
|---|---|---|---|
| TCP | `0.0.0.0/0` (시연용) 또는 내 IP/32 | `22` | SSH |
| TCP | `0.0.0.0/0` (시연용) 또는 팀원 IP | `8000` | FastAPI + WebSocket |

4. 저장

- `0.0.0.0/0` = 전 세계 허용 (시연엔 편함, 보안은 약함)
- 가능하면 팀원 공인 IP만 넣는 편이 안전합니다.

---

## 4. SSH로 서버 접속

NCP Ubuntu는 보통 최초에 **비밀번호**가 필요합니다.

1. 서버 목록에서 해당 서버 체크
2. **서버 관리 및 설정 변경** → **관리자 비밀번호 확인**
3. 다운로드한 `.pem` 인증키로 비밀번호 복호화/확인
4. 터미널에서 접속:

```bash
chmod 400 ~/Downloads/railtwin-key.pem   # 경로·파일명은 본인 것
ssh -i ~/Downloads/railtwin-key.pem root@공인IP
# 비밀번호 물으면: 위에서 확인한 관리자 비밀번호 입력
```

접속되면 다음 단계로 진행합니다.

---

## 5. Docker 설치 (Ubuntu)

공식 요약 절차:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo \"$VERSION_CODENAME\") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker "$USER"
```

설치 후 **한 번 로그아웃 후 재접속** 하거나:

```bash
sudo docker version
sudo docker compose version
```

---

## 6. 코드 배포

### 방법 A — Git clone (권장)

```bash
cd ~
git clone https://github.com/liebe1127/HP028_RailTwin.git
cd HP028_RailTwin
```

(레포 URL이 다르면 팀 실제 주소로 바꿉니다.)

### 방법 B — 내 PC에서 파일 복사

```bash
# 내 PC에서 실행
scp -i 키.pem -r /Users/나/Developer/해운물류0717 root@공인IP:~/HP028_RailTwin
```

### 환경 파일

```bash
cd ~/HP028_RailTwin
cp .env.example .env
# nano .env에서 SENSOR_AUTH_TOKEN을 긴 임의 문자열로 변경
# 합성 시연: DEMO_MODE=true
# 실제 ESP32-C3: DEMO_MODE=false, 펌웨어 secrets.h에도 같은 토큰 설정
```

모델 파일 `rbf_dummy_model.pth` 는 git에 없을 수 있습니다.  
없어도 됩니다 — 컨테이너 시작 시 **자동으로 더미 모델을 학습**합니다.

---

## 7. 컨테이너 실행

```bash
cd ~/HP028_RailTwin
sudo docker compose up -d --build
```

첫 빌드는 torch 때문에 **수 분** 걸릴 수 있습니다.

상태 확인:

```bash
sudo docker compose ps
sudo docker compose logs -f --tail=50
```

로그에 `Application startup complete` / 더미 스트리머 시작 메시지가 보이면 성공입니다.

중지:

```bash
sudo docker compose down
```

---

## 8. 동작 확인

브라우저에서:

```
http://공인IP:8000/
```

예시 응답:

```json
{
  "status": "ok",
  "demo_mode": true,
  "sensor_ws_clients": 0,
  "ai_model_loaded": true
}
```

웹 대시보드(선택):

1. 로컬에서 `frontend/index.html` 열기
2. 페이지 안 WebSocket 주소가 `ws://127.0.0.1:8000/ws` 라면  
   → 공인 IP로 바꾼 뒤 새로고침  
   (파일에 주소가 하드코딩돼 있으면 그 부분만 수정)

---

## 9. Godot에서 원격 접속 (팀원 PC)

1. Godot **4.7**에서 씬 실행 준비
2. `rail_twin_websocket.gd` 가 붙은 노드 선택
3. Inspector → **Websocket Url** 을 다음으로 변경:

```
ws://공인IP:8000/ws
```

예: `ws://203.0.113.10:8000/ws`

4. Crane Path / Rail Path 지정 후 ▶ Play  
5. 크레인이 움직이고, 레일 구간 색(`rail_risk`)이 칠해지면 성공

로컬 서버로 다시 볼 때는:

```
ws://127.0.0.1:8000/ws
```

---

## 10. 자주 겪는 문제

| 증상 | 확인 |
|---|---|
| VPC/Subnet 선택 칸이 비어 있음 | **§1 VPC + Public Subnet** 먼저 생성 |
| 서버는 있는데 밖에서 접속 안 됨 | Subnet이 **Public**인지, **공인 IP** 붙었는지, ACG 22/8000 |
| 브라우저가 안 열림 | ACG 8000, `docker compose ps` 가 Up 인지 |
| Godot 연결 실패 | URL이 `ws://` 인지, 공인 IP·포트 오타 |
| 빌드 메모리 부족 | 서버 RAM 4GB 미만이면 스펙 업 |
| `ai_model_loaded: false` | `docker compose logs` 확인 |
| `influx_write_enabled: false` | `.env`의 Influx 토큰·조직이 비어 있어 DB 쓰기만 비활성화된 상태 |

---

## 11. 팀원에게 공유할 한 줄

```
서버: https://hp028-railtwin.duckdns.org/
Godot WebSocket: wss://hp028-railtwin.duckdns.org/ws
```

---

## 12. HTTPS / WSS (Nginx 없이 Uvicorn SSL)

인증서는 Certbot standalone으로 이미 발급된 상태를 가정합니다.

- fullchain: `/etc/letsencrypt/live/hp028-railtwin.duckdns.org/fullchain.pem`
- privkey: `/etc/letsencrypt/live/hp028-railtwin.duckdns.org/privkey.pem`
- ACG: **443** (및 갱신용 **80**) 허용

### Docker (권장 — 현재 NCP 운영 방식)

```bash
cd ~/해운물류0717   # 실제 클론 경로
docker compose down
docker compose -f docker-compose.https.yml up -d --build
docker compose -f docker-compose.https.yml ps
curl -I https://hp028-railtwin.duckdns.org/
```

### 호스트에서 직접 uvicorn

```bash
sudo bash scripts/run_https.sh
```

### 팀원 접속

| 용도 | URL |
|---|---|
| 헬스/API | `https://hp028-railtwin.duckdns.org/` |
| ESP32-C3 센서 업링크 | `wss://hp028-railtwin.duckdns.org/ws/sensor` |
| Godot / 대시보드 WS | `wss://hp028-railtwin.duckdns.org/ws` |

로컬 HTTP 개발으로 되돌릴 때: `docker compose -f docker-compose.yml up -d --build`  
프론트 로컬 WS: `frontend/index.html?ws=ws://127.0.0.1:8000/ws`

### 인증서 갱신 참고

`certbot renew` 가 standalone이면 **80** 포트가 비어 있어야 합니다. uvicorn은 **443**만 쓰므로 보통 문제 없습니다. 갱신 실패 시 컨테이너를 잠시 내리고 갱신한 뒤 다시 올리면 됩니다.

---

## 참고 (다음에 할 수 있는 것)

- ACG에서 팀원 IP만 허용
- `SENSOR_AUTH_TOKEN` 주기적 교체와 장치별 토큰 분리
- 트래픽·인증서 자동 갱신을 더 편하게 쓰려면 이후 Nginx 리버스 프록시로 전환
