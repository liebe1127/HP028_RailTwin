# MacBook M5 Pro 작업환경 · 온보딩

> 기준일: 2026-09-17. 이 맥에서 실제로 확인한 설치 상태를 기준으로 한다.  
> 3D 범위: **레일 두 줄만**. 크레인 메시·Godot는 현재 작업이 아니다.

이 문서는 사람이 따라 하는 온보딩이다. AI 채팅용 원칙은 [`핵심기술스택과_작업절차_AI학습용_Tech-Stack-and-Workflow.md`](핵심기술스택과_작업절차_AI학습용_Tech-Stack-and-Workflow.md)를 쓴다.

---

## 0. 이 맥에 이미 있는 것

| 항목 | 상태 (2026-09-17 확인) |
|---|---|
| 칩 | Apple M5, arm64 |
| Unity Hub | `/Applications/Unity Hub.app` |
| Unity Editor | **6000.6.0f1** Apple Silicon (프로젝트와 동일) |
| Web Build Support (WebGL) | 설치됨 |
| Unity 라이선스 파일 | `~/Library/Unity/licenses` 존재 |
| Python | 시스템 3.9.6, FastAPI·numpy·paho 사용 가능 |
| `.env` | 저장소 루트에 있음 |
| 대시보드용 WebGL 산출물 | `frontend/unity/Build/` 있음 |
| Arduino IDE + `arduino-cli` | ESP32 코어 3.3.11, 펌웨어 라이브러리 설치됨 |
| Docker / 로컬 Mosquitto | 없음. 더미 시연에는 필요 없음 |

추가로 깔 엔진은 없다. 할 일은 **Hub에 프로젝트를 연결하고, Cursor를 코드 편집기로 잡고, Play → 대시보드 루프를 한 번 도는 것**이다.

Android Build Support가 같이 깔려 있어도 이 프로젝트는 쓰지 않는다. Windows/iOS 모듈을 더 받지 않아도 된다.

---

## 1. Unity Hub에서 할 일 (첫날, 10분)

1. Unity Hub를 연다.
2. 로그인 후 라이선스가 **Personal**(또는 Education/Pro)인지 확인한다. 에디터가 라이선스 창에서 멈추면 여기서 막힌 것이다.
3. **Installs**에서 `6000.6.0f1` → 톱니바퀴 → **Add modules**.
   - **Web Build Support** 가 체크되어 있어야 한다. 이미 있으면 그대로 둔다.
   - Visual Studio / VS Code 모듈은 있어도 되고, 코드는 Cursor로 연다.
4. **Projects → Add → Add project from disk**  
   폴더: `unity/RailTwinRails`  
   **저장소 루트(`해운물류0717(최신)`)를 Unity 프로젝트로 열지 않는다.**
5. 버전이 `6000.6.0f1`인지 보고 Open.

터미널에서 바로 열려면 아래를 실행하거나, [`unity/Unity에서_레일씬열기.command`](../unity/Unity에서_레일씬열기.command)를 더블클릭한다.

```bash
open -a "/Applications/Unity/Hub/Editor/6000.6.0f1/Unity.app" \
  --args -projectPath "$(pwd)/unity/RailTwinRails"
```

첫 실행은 `Library/`를 만들면서 1~3분 걸린다. 에러 없이 Hierarchy에 `RailTwin`, `Main Camera`, `Directional Light`가 보이면 성공이다.

### Cursor를 Unity 스크립트 편집기로

Unity 메뉴 **Unity → Settings → External Tools**:

- External Script Editor → **Browse** → `/Applications/Cursor.app`
- Generate .csproj files for: 기본값으로 충분하다.

이제 `RailTwinController.cs`를 더블클릭하면 Cursor가 열린다.

---

## 2. 에디터에서 확인하는 순서

1. `Assets/Scenes/RailTwin` 씬이 열려 있는지 본다.
2. Hierarchy에서 **RailTwin** 오브젝트를 고르고 Inspector에 `RailTwinController`가 붙어 있는지 본다.
3. 재생(Play)을 누른다.
4. Game 뷰에 남색 배경, 파란 레일 두 줄, 흰 마커가 보여야 한다. Play 중에는 대시보드 데이터가 안 들어온다. 색이 바뀌는 확인은 3절 WebGL이다.
5. Play를 끈다.
6. 레일 모양·색 로직은 `Assets/Scripts/RailTwinController.cs`만 고친다. 크레인 FBX를 넣지 않는다.

JS가 보내는 계약:

```text
SendMessage("RailTwin", "ApplyState", json)
json = {"x":45,"len":100,"n":20,"l":[...],"r":[...]}
```

오브젝트 이름 `RailTwin`과 메서드 `ApplyState`를 바꾸면 대시보드가 끊긴다.

---

## 3. WebGL → 대시보드 (매일 루프)

레일 스크립트나 씬을 바꾼 뒤:

```bash
# 저장소 루트에서
UNITY="/Applications/Unity/Hub/Editor/6000.6.0f1/Unity.app/Contents/MacOS/Unity"
"$UNITY" -batchmode -nographics -quit \
  -projectPath "$(pwd)/unity/RailTwinRails" \
  -executeMethod RailTwinWebGLBuild.Build \
  -logFile unity-webgl-build.log

bash scripts/sync_unity_webgl.sh
```

에디터 GUI에서 빌드해도 된다: **File → Build Profiles → Web**, output을 `unity/RailTwinRails/Build/WebGL`로 둔 다음 `sync_unity_webgl.sh`를 실행한다. 배치 빌드는 씬을 `EnsureScene()`으로 다시 쓰기 때문에, 에디터에서 손으로 배치한 오브젝트는 배치 빌드에 안 남는다. 로직은 스크립트에 두는 것이 안전하다.

대시보드 시연:

```bash
# 저장소 루트, .env 의 DEMO_MODE=true
python3 -m uvicorn main:app --host 127.0.0.1 --port 8000
```

브라우저: [http://127.0.0.1:8000/dashboard](http://127.0.0.1:8000/dashboard)

성공 기준:

- 단계 3 상태가 `Unity WebGL`
- 레일은 각파이프 5개, 300 cm. 더미 색은 시작 쪽 20–90 cm(첫·둘째 파이프)에 있다
- LEFT `demo-left`, RIGHT `demo-right`

Unity 산출물이 없으면 대시보드가 2D 레일 폴백을 쓴다. 그건 엔진이 고장난 것이 아니라 빌드·복사가 안 된 것이다.

환경이 맞는지 보려면:

```bash
bash scripts/check_dev_environment.sh
```

---

## 4. 백엔드·펌웨어는 언제 손대나

| 역할 | 이 맥에서 바로 | 나중에 |
|---|---|---|
| 웹 + Unity 레일 (김병서) | 1~3절 | 결함 종류 이름 |
| 규칙 엔진 (배준호) | `python3 -m pytest tests/` (pytest 설치 후) | 실측 임계값 |
| 펌웨어 (배용진) | Arduino IDE로 `firmware/esp32_c3_rail_sensor/` | 실물 업로드·교정 |
| 모형 주행 (김정우) | — | 반복 주행·라벨 |

pytest가 없으면:

```bash
python3 -m pip install --user pytest
python3 -m pytest tests/ -q
```

펌웨어는 Arduino IDE에서 보드 **ESP32C3 Dev Module**, 스케치북 경로는 저장소의 `firmware/esp32_c3_rail_sensor/`다. `secrets.h`와 `node_profile.h`는 Git에 올리지 않는다. 좌 프로필을 양쪽 보드에 올리지 않는다.

로컬 Mosquitto·Docker·InfluxDB는 **실물 MQTT 입력**을 이 맥에서 받을 때만 필요하다. 지금은 `DEMO_MODE=true`로 웹·Unity를 만든다.

---

## 5. Cursor 온보딩 (새 채팅)

새 에이전트 채팅 첫 메시지 예:

```text
@docs/mac-m5-unity-onboarding.md
@docs/notion-project-context.md
@unity/RailTwinRails/Assets/Scripts/RailTwinController.cs

이 맥은 Unity 6000.6.0f1 + WebGL이 설치된 M5 Pro다.
3D는 레일만 다룬다. Godot·크레인 메시·RBF·웨이블릿은 쓰지 마라.
지금은 Unity 씬/스크립트와 대시보드 연동만 작업한다.
```

항상 적용되는 규칙은 `.cursor/rules/rail-deformation-context.mdc`다.

하지 말 것:

- 거더 처짐 / `deflection` 을 새로 쓰기
- `predict_rail_deform`, PyTorch RBF, 웨이블릿, CREST 를 목표 스택으로 넣기
- Godot 프로젝트를 다시 살리기
- 상용 크레인 모델을 공개 저장소에 넣기

---

## 6. 막히면

| 증상 | 볼 곳 |
|---|---|
| Hub가 버전을 바꾸자고 함 | 6000.6.0f1을 고른다. 업그레이드하지 않는다 |
| Play는 되는데 대시보드가 하얗다 | `scripts/sync_unity_webgl.sh` 후 강력 새로고침. 상태는 `Unity WebGL`이어야 한다 |
| 배치 빌드 실패 | `unity-webgl-build.log` 끝부분 |
| WebGL 모듈 없음 | Hub → 6000.6.0f1 → Add modules → Web Build Support |
| 대시보드 포트 충돌 | `lsof -i :8000` 후 기존 uvicorn 종료 |
| Camera.main / SendMessage 실패 | Hierarchy 이름이 정확히 `RailTwin`인지 |

자세한 빌드 한 줄은 [`unity/RailTwinRails/README.md`](../unity/RailTwinRails/README.md).
