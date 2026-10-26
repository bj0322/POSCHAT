# 업데이트 서버 운영

저장소가 비공개여도 앱이 자동 업데이트를 받도록 PIDS Tech. 서버(`updates.UPDATE_BASE_URL`)가 새 릴리스를 나눠 줍니다. 앱 쪽은 `updates.py`, 서명은 [security.md](security.md#업데이트-신뢰-모델).

## 구조
```
GitHub 릴리스(CI가 서명 파일 .sig까지 올림)
   └─ 서버의 poschat-update-sync.timer(10분마다) ─ /opt/poschat-update/poschat-sync.py
        └─ publish.py → /var/www/updates/{api/releases/latest, releases/download/<태그>/…}
             └─ nginx(80)가 그대로 줌 ─ 앱: GET /api/releases/latest, /releases/download/<태그>/<파일>(.sig)
```
- 피드는 GitHub `releases/latest`와 같은 모양의 JSON(`tag_name`·`name`·`body`·`assets[name,size,digest,browser_download_url]`)입니다.
- 서버에는 서명 개인키가 없습니다. 동기화 스크립트는 파일마다 GitHub가 알려 주는 크기·SHA-256을 확인하고, 앱이 서명을 다시 확인합니다.
- 최신 버전은 `/releases/download/latest/<파일>` 링크로도 받을 수 있습니다. 서버에는 최근 2개 버전만 둡니다.
- 서버의 스크립트(저장소 밖): `/opt/poschat-update/poschat-sync.py`, `publish.py`, systemd 유닛 `poschat-update-sync.{service,timer}`.

## 저장소를 비공개로 바꿀 때
GitHub가 비공개이면 서버가 릴리스를 가져오려면 읽기 전용 토큰이 필요합니다.
1. GitHub → Settings → Developer settings → Fine-grained tokens: 저장소 `bj0322/POSCHAT`만, 권한은 **Contents: Read-only**(Metadata는 자동).
2. 서버에서 `/etc/poschat-update.env`(소유 root:pidsdeploy, 권한 0640)에 `GITHUB_TOKEN=<토큰>` 한 줄을 넣습니다.
3. `sudo systemctl start poschat-update-sync.service`, `journalctl -u poschat-update-sync.service`로 확인합니다.
토큰은 GitHub로 가는 요청에만 쓰고, 저장소 밖 서명 URL로 리디렉션될 때는 보내지 않습니다.

## 점검
- 피드: `curl http://3.38.118.65/api/releases/latest`
- 마지막 동기화: `journalctl -u poschat-update-sync.service -n 20`, 다음 실행: `systemctl list-timers poschat-update-sync.timer`
- 지금 바로 동기화: `sudo systemctl start poschat-update-sync.service`
- 디스크: `df -h /var/www` (릴리스 하나가 약 300MB, 동기화 중에는 두 배)
