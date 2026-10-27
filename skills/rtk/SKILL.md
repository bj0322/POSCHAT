---
name: rtk
description: 코드 작업에서 RTK를 사용해 Git 상태나 지원하는 시험 명령의 출력을 간결하게 살펴볼 때 사용. RTK 설치와 사용을 요청한 경우에도 사용.
---

# RTK 명령 출력 줄이기

RTK는 별도 실행 파일이다. POSCHAT이 RTK를 포함하거나 자동으로 설치하지 않는다. 사용자 PC 또는 원격 작업 폴더에서 실행할 컴퓨터에 RTK가 있고 PATH에서 찾을 수 있어야 한다. 없다면 기존 명령으로 작업을 계속하고, 사용자가 원하면 RTK OSS 설치 안내를 제공한다.

- RTK가 설치되어 있는지 기존 명령 실행 도구로 `rtk --version`을 확인한다. 원격 작업이면 원격 환경에서 확인한다.
- 지원되는 명령에 한해 `rtk git status`, `rtk git diff`, `rtk pytest`처럼 RTK를 명시적으로 호출한다. 옵션과 지원 여부는 해당 버전의 `rtk --help`와 공식 문서에서 확인한다.
- 명령은 POSCHAT의 기존 실행 승인과 권한 모드를 따른다. 승인된 명령을 실행 전에 몰래 바꾸지 않는다. 셸 연결, 리다이렉션, 대화형 명령이나 변경·삭제 명령은 자동으로 변환하지 않는다.
- 출력이 일부 생략될 수 있다. 변경 내용, 정확한 오류나 시험 결과를 판단하기에 불충분하면 원래 명령을 다시 실행해 확인한다. 실패한 변경 명령을 무심코 재실행하지 않는다.
- `rtk gain`의 수치는 추정치다. 전체 토큰이나 비용이 같은 비율로 줄었다고 주장하지 않는다.
- RTK의 다른 에이전트용 훅과 `rtk init`은 POSCHAT에 자동 연결되지 않는다. 사용자 동의 없이 다른 도구의 설정을 바꾸지 않는다.

설치: macOS는 `brew install rtk-ai/tap/rtk-oss`, Windows는 [RTK 릴리스](https://github.com/rtk-ai/rtk/releases)에서 `rtk-oss-x86_64-pc-windows-msvc.zip`을 받아 압축을 풀고 `rtk.exe`를 PATH에 추가한다. 설치 뒤 새 터미널에서 `rtk --version`과 `rtk gain`을 확인하고 POSCHAT을 다시 시작한다. 설치와 다운로드는 사용자가 결정하며, RTK 전체판과 OSS판은 이름이 같으므로 혼동하지 않는다.
