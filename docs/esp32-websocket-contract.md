# ESP32-C3 업링크 계약 (이동됨)

센서 업링크는 WebSocket `/ws/sensor`가 아니라 MQTTS QoS 1이다.

현재 계약은 [`docs/esp32-mqtt-contract.md`](esp32-mqtt-contract.md)를 따른다. 화면 다운링크만 기존처럼 `wss://host/ws`를 사용한다.
