# Unity 레일 WebGL

3D는 **레일 두 줄만** 다룬다. 크레인 상용 모델은 넣지 않는다. 각 줄은 아연 각파이프(25×25 mm, 60 cm) 5개를 이은 300 cm이고, 이음만 밝은 띠로 구분한다.

Mac 온보딩(Hub에 프로젝트 추가, Cursor 연결, Play 확인)은 [`docs/mac-m5-unity-onboarding.md`](../../docs/mac-m5-unity-onboarding.md)다. 에디터는 **6000.6.0f1** + **Web Build Support**가 필요하다. 저장소 루트가 아니라 이 폴더(`unity/RailTwinRails`)를 연다.

바로 열려면 상위 폴더의 [`Unity에서_레일씬열기.command`](../Unity에서_레일씬열기.command)를 더블클릭한다.

## 빌드

Unity 6 (6000.6) WebGL 모듈이 필요하다.

```bash
UNITY="/Applications/Unity/Hub/Editor/6000.6.0f1/Unity.app/Contents/MacOS/Unity"
"$UNITY" -batchmode -nographics -quit \
  -projectPath "$(pwd)/unity/RailTwinRails" \
  -executeMethod RailTwinWebGLBuild.Build \
  -logFile unity-webgl-build.log
```

산출물은 `unity/RailTwinRails/Build/WebGL/` 이다. 대시보드는 `/unity/Build/*.loader.js` 를 찾으므로 빌드 후 `Build/` 안의 파일을 `frontend/unity/Build/` 로 복사한다.

`scripts/sync_unity_webgl.sh` 가 그 복사를 한다.
